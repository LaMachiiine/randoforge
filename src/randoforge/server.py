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
from .core import loops
from .core import pois as poi_lib
from .core import technical as technical_lib
from .core.geo import densify
from .core.models import (
    ElevationParams,
    Poi,
    Route,
    RouteRequest,
    RouteSummary,
    TechnicalPassage,
    TrackPoint,
    ValidationReport,
    WalkerProfile,
)
from .core.stats import compute_stats as _compute_stats
from .core.terrain import retraced_sections
from .engines.brouter import BRouterEngine
from .engines.elevation import CopernicusElevation, ElevationChain, IgnElevation
from .engines.osm import Nominatim, Overpass, Place
from .formats.gpx import read_gpx, write_gpx
from .formats.html import write_map
from .formats.markdown import write_fiche
from .http import CachedHttp, HttpError
from .storage import RouteStore, default_home, new_route_id
from .validation import tarmac_length, validate

INSTRUCTIONS = """\
RandoForge fournit des outils fiables pour concevoir des itinéraires de randonnée.
Règles :
- N'annonce jamais une distance, un dénivelé, une durée ou une altitude qui ne vient pas d'un outil.
- Ne propose jamais un tracé qui n'a pas été produit par route_between (ou importé).
- Lance validate_route avant de livrer ; ne livre pas un itinéraire au statut `error` sans le dire.
- Signale toujours à l'utilisateur les `warnings` et les checks de validation.
Démarche type : geocode → find_pois → route_between (ou generate_loop_candidates + compare_routes)
→ annotate_route → technical_passages → validate_route → export_route.
"""

DENSIFY_M = 10.0
CategoryName = Literal["cascade", "point_de_vue", "lac", "sommet", "curiosite", "riviere", "patrimoine", "eau", "pause"]
ALL_CATEGORIES: list[str] = list(poi_lib.CATEGORIES)
SacScale = Literal["hiking", "mountain_hiking", "demanding_mountain_hiking", "alpine_hiking", "demanding_alpine_hiking"]
Profile = Literal["hiking-mountain", "hiking-beta", "shortest"]
WALKERS = {
    "famille": WalkerProfile(flat_kmh=3.0, up_m_per_h=200, down_m_per_h=350),
    "moyen": WalkerProfile(),
    "sportif": WalkerProfile(flat_kmh=5.0, up_m_per_h=450, down_m_per_h=700),
}


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


class LoopCandidate(BaseModel):
    route: RouteSummary
    bearing_deg: float = Field(description="Direction générale de la boucle depuis le départ (0 = nord)")
    retrace_km: float = Field(description="Distance parcourue deux fois (aller-retour)")
    tarmac_pct: float
    score: float = Field(description="Plus petit = plus proche de la demande")


class LoopCandidates(BaseModel):
    candidates: list[LoopCandidate]
    tried: int
    failed: int
    notes: list[str]


class ComparisonRow(BaseModel):
    route_id: str
    name: str
    distance_km: float | None
    d_plus_m: float | None
    duree: str | None
    alt_max_m: float | None
    tarmac_pct: float | None
    retrace_km: float
    niveau_technique_max: str | None
    n_passages_techniques: int | None
    n_pois: int | None
    validation: str | None


class Comparison(BaseModel):
    rows: list[ComparisonRow]


class TechnicalResult(BaseModel):
    route_id: str
    passages: list[TechnicalPassage]
    niveau_max: str | None
    notes: list[str]


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

    def make_route(
        wps: list[tuple[float, float]],
        required: list[tuple[float, float]],
        profile: str,
        loop: bool,
        name: str,
        max_sac_scale: str | None,
        with_dem: bool = True,
    ) -> Route:
        """Tracé BRouter + altimétrie MNT + stats, non enregistré.
        `required` : points imposés par l'utilisateur (vérifiés par la règle G6)."""
        result = external(lambda: services.router.route(wps, profile))
        route = Route(
            route_id=new_route_id(),
            name=name,
            source=f"BRouter:{profile}",
            points=result.points,
            waypoints=required,
            request=RouteRequest(loop=loop, max_sac_scale=max_sac_scale),
            segments=result.segments,
            engine_stats=result.engine_stats,
        )
        if with_dem:
            apply_dem(route)
            stats_into(route)
        return route

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
        profile: Profile = "hiking-mountain",
        loop: bool = False,
        name: str | None = None,
        max_sac_scale: SacScale | None = None,
    ) -> RouteSummary:
        """Calcule un tracé sur de vrais chemins passant par les points donnés, dans l'ordre.

        - `loop=True` : revient au premier point (boucle).
        - `max_sac_scale` : difficulté maximale acceptée (hiking = T1 facile … alpine_hiking = T4) ;
          vérifiée par validate_route.
        Distance et dénivelé sont recalculés sur un MNT précis (IGN en France, Copernicus ailleurs).
        """
        required = [(w.lat, w.lon) for w in waypoints]
        wps = required + [required[0]] if loop and required[0] != required[-1] else list(required)
        route = make_route(wps, required, profile, loop, name or f"Itinéraire {profile}", max_sac_scale)
        store.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def generate_loop_candidates(
        start: LatLon,
        distance_km: Annotated[float, Field(ge=2, le=60)],
        d_plus_m: Annotated[float | None, Field(ge=0, le=5000)] = None,
        n: Annotated[int, Field(ge=1, le=5)] = 3,
        directions: Annotated[int, Field(ge=3, le=12)] = 6,
        profile: Profile = "hiking-mountain",
        max_sac_scale: SacScale | None = None,
        name: str | None = None,
    ) -> LoopCandidates:
        """Génère automatiquement des boucles depuis un départ pour une distance (et un D+) cible,
        dans plusieurs directions, et renvoie les `n` meilleures, déjà mesurées sur le MNT.

        Classement : écart à la distance et au D+ demandés, pénalité pour les allers-retours
        et le goudron. Pour imposer un lieu (cascade, sommet), utiliser plutôt route_between
        avec loop=True. Prévoir ~20–40 s (une dizaine de calculs de tracé).
        """
        origin = (start.lat, start.lon)
        target_m = distance_km * 1000
        tried = failed = 0
        drafts: list[tuple[float, Route, float, float]] = []  # (direction, tracé, aller-retour m, goudron m)
        for bearing in loops.bearings(directions):
            radius = loops.initial_radius(target_m)
            best: Route | None = None
            for _ in range(2):  # un essai + une correction de taille
                tried += 1
                try:
                    draft = make_route(
                        loops.triangle(origin, bearing, radius),
                        [origin],
                        profile,
                        True,
                        "",
                        max_sac_scale,
                        with_dem=False,
                    )
                except ToolError:
                    failed += 1
                    break
                actual = draft.engine_stats.get("distance_m") or 0
                if best is None or abs(actual - target_m) < abs(best.engine_stats.get("distance_m", 0) - target_m):
                    best = draft
                if abs(actual - target_m) / target_m < 0.08:
                    break
                radius = loops.corrected_radius(radius, target_m, actual)
            if best is not None:
                retrace = sum(sec.value for sec in retraced_sections(best.points))
                drafts.append((bearing, best, retrace, tarmac_length(best.segments)))
        if not drafts:
            raise ToolError(
                "Aucune boucle trouvée : le départ est peut-être loin de tout chemin. Essayer geocode ou find_pois."
            )

        def pre_score(d) -> float:
            _, r, retrace, tarmac = d
            return loops.score(r.engine_stats["distance_m"], target_m, None, None, retrace, tarmac).total

        # Mesure fine (MNT) seulement pour les meilleurs brouillons : économise les appels d'altimétrie.
        scored = []
        for bearing, r, retrace, tarmac in sorted(drafts, key=pre_score)[: n + 2]:
            apply_dem(r)
            stats_into(r)
            sc = loops.score(r.stats.distance_km * 1000, target_m, r.stats.d_plus_m, d_plus_m, retrace, tarmac)
            scored.append((sc.total, bearing, r, retrace, tarmac))
        scored.sort(key=lambda x: x[0])

        compass = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
        candidates = []
        for i, (total, bearing, r, retrace, tarmac) in enumerate(scored[:n], 1):
            r.name = f"{name or 'Boucle'} {i} ({compass[round(bearing / 45) % 8]})"
            store.save(r)
            candidates.append(
                LoopCandidate(
                    route=RouteSummary.of(r),
                    bearing_deg=bearing,
                    retrace_km=round(retrace / 1000, 2),
                    tarmac_pct=round(100 * tarmac / max(1.0, r.engine_stats.get("distance_m", 0))),
                    score=round(total, 3),
                )
            )
        notes = []
        if d_plus_m and all(abs((c.route.stats.d_plus_m or 0) - d_plus_m) / d_plus_m > 0.25 for c in candidates):
            notes.append(
                "Aucune boucle n'approche le D+ demandé à 25 % près : "
                "le relief autour du départ ne s'y prête peut-être pas."
            )
        if failed:
            notes.append(f"{failed} essai(s) sans chemin praticable.")
        return LoopCandidates(candidates=candidates, tried=tried, failed=failed, notes=notes)

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
        walker: Literal["famille", "moyen", "sportif"] | None = None,
    ) -> RouteSummary:
        """Recalcule distance, D+/D-, altitudes et durée avec d'autres paramètres.

        `walker` applique un profil prédéfini qui remplace les vitesses (famille : 3 km/h et
        200 m/h en montée ; moyen : 4 km/h et 300 m/h ; sportif : 5 km/h et 450 m/h).
        Les paramètres de lissage par défaut conviennent à la plupart des cas.
        """
        route = load(route_id)
        params = ElevationParams(step_m=step_m, smooth_window_m=smooth_window_m, threshold_m=threshold_m)
        if walker:
            profile = WALKERS[walker]
        else:
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
    def technical_passages(route_id: str) -> TechnicalResult:
        """Indique les passages techniques au km près : difficulté T3+ (échelle CAS), pentes fortes,
        via ferrata, échelles, câbles, sentier peu visible, pierriers, glaciers, dangers signalés.

        Chaque passage précise pourquoi il est signalé (sources). `a_verifier` = indice douteux.
        """
        route = load(route_id)
        query = technical_lib.build_query(route.points)
        elements = external(lambda: services.overpass.query(query))
        route.technical = technical_lib.technical_passages(
            route.points, route.segments, elements, route.engine_stats.get("distance_m")
        )
        route.validation = None
        store.save(route)
        levels = [p.niveau for p in route.technical if p.niveau]
        notes = []
        if not route.segments:
            notes.append(
                "Trace importée : difficulté OSM (sac_scale) non disponible, "
                "seuls la pente et les tags OSM sont analysés."
            )
        if any(p.a_verifier for p in route.technical):
            notes.append("Certains passages sont marqués à vérifier (possible artefact du relief).")
        return TechnicalResult(
            route_id=route_id, passages=route.technical, niveau_max=max(levels, default=None), notes=notes
        )

    @mcp.tool()
    def compare_routes(route_ids: Annotated[list[str], Field(min_length=2, max_length=10)]) -> Comparison:
        """Tableau comparatif de plusieurs itinéraires (distance, D+, durée, goudron, allers-retours,
        difficulté technique, points notables, validation) pour aider à choisir."""
        rows = []
        for rid in route_ids:
            r = load(rid)
            s = r.stats
            levels = [p.niveau for p in r.technical or [] if p.niveau]
            engine_m = r.engine_stats.get("distance_m")
            rows.append(
                ComparisonRow(
                    route_id=rid,
                    name=r.name,
                    distance_km=s.distance_km if s else None,
                    d_plus_m=s.d_plus_m if s else None,
                    duree=s.duration_label if s else None,
                    alt_max_m=s.alt_max_m if s else None,
                    tarmac_pct=round(100 * tarmac_length(r.segments) / engine_m) if r.segments and engine_m else None,
                    retrace_km=round(sum(sec.value for sec in retraced_sections(r.points)) / 1000, 2),
                    niveau_technique_max=max(levels, default=None),
                    n_passages_techniques=len(r.technical) if r.technical is not None else None,
                    n_pois=len(r.pois) if r.pois is not None else None,
                    validation=r.validation.status if r.validation else None,
                )
            )
        return Comparison(rows=rows)

    @mcp.tool()
    def validate_route(route_id: str) -> ValidationReport:
        """Vérifie l'itinéraire : géométrie, accès interdits, difficulté, cohérence des chiffres,
        passages raides, gués. Statut `ok`, `warning` ou `error` avec la position au km.

        Lance automatiquement annotate_route et technical_passages si ce n'est pas déjà fait.
        """
        route = load(route_id)
        for missing, tool in ((route.pois is None, annotate_route), (route.technical is None, technical_passages)):
            if missing:
                try:
                    tool(route_id)
                except ToolError:
                    pass  # Overpass indisponible : les règles concernées le signalent en `info`
        route = load(route_id)
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
    def export_route(
        route_id: str,
        formats: list[Literal["gpx", "md", "html"]] = ["gpx", "md", "html"],  # noqa: B006
    ) -> ExportResult:
        """Écrit les fichiers d'un itinéraire : GPX (montre, applis, avec les points notables)
        et/ou fiche Markdown (Obsidian) et/ou carte HTML (fond topo, points notables, passages
        techniques, profil altimétrique). Renvoie les chemins, à communiquer à l'utilisateur.
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
        if "html" in formats:
            (d / "carte.html").write_text(write_map(route), encoding="utf-8")
            files["html"] = str(d / "carte.html")
        return ExportResult(route_id=route_id, files=files)

    return mcp


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
