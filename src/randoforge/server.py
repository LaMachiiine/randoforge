"""Serveur MCP RandoForge : expose à Claude des outils déterministes pour les itinéraires de rando."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from . import __version__
from .core import pois as poi_lib
from .core.geo import densify
from .core.models import (
    ElevationParams,
    Poi,
    Route,
    RouteRequest,
    RouteSummary,
    TrackPoint,
    ValidationReport,
    WalkerProfile,
)
from .core.stats import compute_stats as _compute_stats
from .engines.brouter import BRouterEngine
from .engines.elevation import CopernicusElevation, ElevationChain, IgnElevation
from .engines.osm import Nominatim, Overpass, Place
from .formats.gpx import read_gpx, write_gpx
from .formats.markdown import write_fiche
from .http import CachedHttp, HttpError
from .storage import RouteStore, default_home, new_route_id
from .validation import validate

INSTRUCTIONS = """\
RandoForge fournit des outils fiables pour concevoir des itinéraires de randonnée.
Règles :
- N'annonce jamais une distance, un dénivelé, une durée ou une altitude qui ne vient pas d'un outil.
- Ne propose jamais un tracé qui n'a pas été produit par route_between (ou importé).
- Lance validate_route avant de livrer ; ne livre pas un itinéraire au statut `error` sans le dire.
- Signale toujours à l'utilisateur les `warnings` et les checks de validation.
Démarche type : geocode → find_pois → route_between → annotate_route → validate_route → export_route.
"""

DENSIFY_M = 10.0
CategoryName = Literal["cascade", "point_de_vue", "lac", "sommet", "curiosite", "riviere", "patrimoine", "eau", "pause"]
ALL_CATEGORIES: list[str] = list(poi_lib.CATEGORIES)


class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RouteList(BaseModel):
    routes: list[RouteSummary]


class ExportResult(BaseModel):
    route_id: str
    files: dict[str, str]


class PlaceList(BaseModel):
    places: list[Place]


class PoiNearby(BaseModel):
    poi: Poi
    distance_from_center_m: float


class PoiSearchResult(BaseModel):
    pois: list[PoiNearby]
    truncated: bool
    source: str = "OpenStreetMap (Overpass)"


class AnnotationResult(BaseModel):
    route_id: str
    pois: list[Poi]
    warnings: list[str]
    source: str = "OpenStreetMap (Overpass)"


@dataclass
class Services:
    """Dépendances externes, injectables (les tests fournissent des doublures)."""

    router: object
    elevation: object
    nominatim: object
    overpass: object

    @classmethod
    def from_env(cls, home: Path) -> Services:
        http = CachedHttp(home / "cache.sqlite")
        overpass_urls = [u for u in os.environ.get("RANDOFORGE_OVERPASS_URLS", "").split(",") if u]
        return cls(
            router=BRouterEngine(http, os.environ.get("RANDOFORGE_BROUTER_URL", "https://brouter.de/brouter")),
            elevation=ElevationChain([IgnElevation(http), CopernicusElevation()]),
            nominatim=Nominatim(http),
            overpass=Overpass(http, overpass_urls or None),
        )


def build_server(store: RouteStore | None = None, services: Services | None = None) -> MCPServer:
    store = store or RouteStore()
    services = services or Services.from_env(default_home())
    mcp = MCPServer("randoforge", version=__version__, instructions=INSTRUCTIONS)

    def load(route_id: str) -> Route:
        # Seuls les messages de ToolError sont transmis à Claude : on traduit les erreurs prévues.
        try:
            return store.load(route_id)
        except (KeyError, ValueError) as exc:
            raise ToolError(exc.args[0]) from exc

    def external(call):
        try:
            return call()
        except (HttpError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    def apply_dem(route: Route) -> None:
        """Densifie le tracé et remplace ses altitudes par celles du MNT."""
        lats, lons = densify(
            np.array([p.lat for p in route.points]), np.array([p.lon for p in route.points]), DENSIFY_M
        )
        res = external(lambda: services.elevation.elevations(list(zip(lats.tolist(), lons.tolist(), strict=True))))
        route.points = [TrackPoint(lat=la, lon=lo, ele=e) for la, lo, e in zip(lats, lons, res.values, strict=True)]
        route.elevation_source = res.summary()
        notes = []
        used = {s for s in res.sources if s}
        if len(used) > 1:
            notes.append(
                f"Altitudes de plusieurs sources ({route.elevation_source}) : "
                "possible marche aux changements de source."
            )
        if CopernicusElevation.name in used:
            notes.append(
                "Copernicus est un modèle de surface (cime des arbres incluse) : D+ possiblement surestimé en forêt."
            )
        route.elevation_notes = notes

    def stats_into(route: Route, params: ElevationParams | None = None, profile: WalkerProfile | None = None) -> None:
        stats, warnings = _compute_stats(
            route.points,
            params or (route.stats.params if route.stats else None),
            profile or (route.stats.profile if route.stats else None),
            elevation_source=route.elevation_source,
        )
        route.stats, route.warnings = stats, route.elevation_notes + warnings
        route.validation = None  # les chiffres ont changé : la validation doit être relancée

    # --- Recherche ----------------------------------------------------------------

    @mcp.tool()
    def geocode(query: str, limit: Annotated[int, Field(ge=1, le=10)] = 5, country: str | None = None) -> PlaceList:
        """Trouve les coordonnées d'un lieu (village, sommet, parking, lac…) par son nom.

        `country` : code ISO à 2 lettres (fr, ch, it…) pour lever les ambiguïtés.
        """
        return PlaceList(places=external(lambda: services.nominatim.geocode(query, limit, country)))

    @mcp.tool()
    def find_pois(
        lat: float,
        lon: float,
        radius_km: Annotated[float, Field(gt=0, le=15)] = 3.0,
        categories: list[CategoryName] | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 30,
    ) -> PoiSearchResult:
        """Cherche des points notables autour d'un lieu pour planifier un itinéraire :
        cascades, points de vue, lacs, sommets et cols, curiosités, patrimoine, eau, refuges…

        Résultats triés par intérêt. Seuls les lieux cartographiés dans OpenStreetMap apparaissent.
        """
        cats = list(categories or ALL_CATEGORIES)
        radius_m = radius_km * 1000
        bbox = poi_lib.bbox_around([TrackPoint(lat=lat, lon=lon)], radius_m)
        elements = external(lambda: services.overpass.query(poi_lib.build_query(bbox, cats)))
        found = poi_lib.near_point(lat, lon, elements, cats, radius_m)
        return PoiSearchResult(
            pois=[PoiNearby(poi=p, distance_from_center_m=round(d)) for p, d in found[:limit]],
            truncated=len(found) > limit,
        )

    # --- Construction -------------------------------------------------------------

    @mcp.tool()
    def route_between(
        waypoints: Annotated[list[LatLon], Field(min_length=2, max_length=30)],
        profile: Literal["hiking-mountain", "hiking-beta", "shortest"] = "hiking-mountain",
        loop: bool = False,
        name: str | None = None,
        max_sac_scale: Literal[
            "hiking",
            "mountain_hiking",
            "demanding_mountain_hiking",
            "alpine_hiking",
            "demanding_alpine_hiking",
        ]
        | None = None,
    ) -> RouteSummary:
        """Calcule un tracé sur de vrais chemins passant par les points donnés, dans l'ordre.

        - `loop=True` : revient au premier point (boucle).
        - `max_sac_scale` : difficulté maximale acceptée (hiking = T1 facile … alpine_hiking = T4) ;
          vérifiée par validate_route.
        Distance et dénivelé sont recalculés sur un MNT précis (IGN en France, Copernicus ailleurs).
        """
        wps = [(w.lat, w.lon) for w in waypoints]
        if loop and wps[0] != wps[-1]:
            wps.append(wps[0])
        result = external(lambda: services.router.route(wps, profile))
        route = Route(
            route_id=new_route_id(),
            name=name or f"Itinéraire {profile}",
            source=f"BRouter:{profile}",
            points=result.points,
            waypoints=[(w.lat, w.lon) for w in waypoints],
            request=RouteRequest(loop=loop, max_sac_scale=max_sac_scale),
            segments=result.segments,
            engine_stats=result.engine_stats,
        )
        apply_dem(route)
        stats_into(route)
        store.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def import_gpx(path: str, name: str | None = None, elevation: Literal["dem", "file"] = "dem") -> RouteSummary:
        """Importe un fichier GPX local comme itinéraire et calcule ses statistiques.

        `elevation="dem"` (défaut) recalcule les altitudes sur le MNT, pour des chiffres comparables
        aux itinéraires générés ; `"file"` garde celles du fichier (ex. altimètre barométrique).
        """
        file = Path(path).expanduser()
        if not file.is_file():
            raise ToolError(f"Fichier introuvable : {file}")
        gpx_name, points = read_gpx(file.read_text(encoding="utf-8"))
        if len(points) < 2:
            raise ToolError("Le GPX ne contient pas de trace exploitable (moins de 2 points).")
        route = Route(
            route_id=new_route_id(),
            name=name or gpx_name or file.stem,
            source=f"gpx:{file.name}",
            points=points,
        )
        if elevation == "dem":
            apply_dem(route)
        else:
            route.elevation_source = "fichier GPX"
        stats_into(route)
        store.save(route)
        return RouteSummary.of(route)

    # --- Mesure, annotation, validation ---------------------------------------------

    @mcp.tool()
    def compute_stats(
        route_id: str,
        step_m: float = 10.0,
        smooth_window_m: float = 30.0,
        threshold_m: float = 5.0,
        flat_kmh: float = 4.0,
        up_m_per_h: float = 300.0,
        down_m_per_h: float = 500.0,
    ) -> RouteSummary:
        """Recalcule distance, D+/D-, altitudes et durée avec d'autres paramètres.

        Les valeurs par défaut conviennent à la plupart des cas. Modifier surtout le profil
        marcheur (vitesses) pour adapter la durée au niveau de l'utilisateur.
        """
        route = load(route_id)
        params = ElevationParams(step_m=step_m, smooth_window_m=smooth_window_m, threshold_m=threshold_m)
        profile = WalkerProfile(flat_kmh=flat_kmh, up_m_per_h=up_m_per_h, down_m_per_h=down_m_per_h)
        stats_into(route, params, profile)
        store.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def annotate_route(
        route_id: str,
        categories: list[CategoryName] | None = None,
        max_detour_m: Annotated[float, Field(ge=0, le=1000)] = 300.0,
    ) -> AnnotationResult:
        """Liste les points notables le long du tracé, avec leur position au km :
        cascades, rivières traversées (gués signalés), lacs, points de vue, sommets, patrimoine…

        `max_detour_m` : distance maximale au tracé. Les points sont ajoutés au GPX et à la fiche.
        """
        route = load(route_id)
        cats = list(categories or ALL_CATEGORIES)
        bbox = poi_lib.bbox_around(route.points, max_detour_m + 50)
        elements = external(lambda: services.overpass.query(poi_lib.build_query(bbox, cats)))
        route.pois = poi_lib.annotate(route.points, elements, cats, max_detour_m)
        route.validation = None
        store.save(route)
        warnings = [
            f"Gué au km {p.km:.1f}{' (' + p.nom + ')' if p.nom else ''} : vérifier le niveau d'eau"
            for p in route.pois
            if p.via == "gué"
        ]
        if not route.pois:
            warnings.append(
                "Aucun point notable cartographié dans OSM le long du tracé (couverture parfois incomplète)."
            )
        return AnnotationResult(route_id=route_id, pois=route.pois, warnings=warnings)

    @mcp.tool()
    def validate_route(route_id: str) -> ValidationReport:
        """Vérifie l'itinéraire : géométrie, accès interdits, difficulté, cohérence des chiffres,
        passages raides, gués. Statut `ok`, `warning` ou `error` avec la position au km.

        Lance automatiquement annotate_route si ce n'est pas déjà fait (pour les gués).
        """
        route = load(route_id)
        if route.pois is None:
            try:
                annotate_route(route_id)
                route = load(route_id)
            except ToolError:
                pass  # Overpass indisponible : la règle D7 le signalera en `info`
        route.validation = validate(route)
        store.save(route)
        return route.validation

    # --- Consultation et export -----------------------------------------------------

    @mcp.tool()
    def get_route(route_id: str) -> RouteSummary:
        """Résumé d'un itinéraire (stats, avertissements, statut de validation), sans la géométrie."""
        return RouteSummary.of(load(route_id))

    @mcp.tool()
    def list_routes() -> RouteList:
        """Liste les itinéraires enregistrés."""
        return RouteList(routes=[RouteSummary.of(r) for r in store.list()])

    @mcp.tool()
    def export_route(route_id: str, formats: list[Literal["gpx", "md"]] = ["gpx", "md"]) -> ExportResult:  # noqa: B006
        """Écrit les fichiers d'un itinéraire : GPX (montre, applis, avec les points notables)
        et/ou fiche Markdown (Obsidian). Renvoie les chemins, à communiquer à l'utilisateur.
        """
        route = load(route_id)
        d = store.dir_for(route_id)
        files: dict[str, str] = {}
        if "gpx" in formats:
            (d / "route.gpx").write_text(write_gpx(route), encoding="utf-8")
            files["gpx"] = str(d / "route.gpx")
        if "md" in formats:
            (d / "fiche.md").write_text(write_fiche(route), encoding="utf-8")
            files["md"] = str(d / "fiche.md")
        return ExportResult(route_id=route_id, files=files)

    return mcp


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
