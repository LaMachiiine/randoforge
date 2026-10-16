"""Contexte partagé par les outils MCP : stockage, services externes, opérations communes."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from mcp.server.mcpserver.exceptions import ToolError

from .core import areas as areas_lib
from .core import loops
from .core import pois as poi_lib
from .core import technical as technical_lib
from .core.geo import densify
from .core.models import ElevationParams, Route, RouteRequest, TrackPoint, WalkerProfile
from .core.stats import compute_stats
from .engines.elevation import CopernicusElevation
from .http import HttpError
from .services import Services
from .storage import RouteStore, new_route_id
from .validation import validate

DENSIFY_M = 10.0
DEFAULT_CATEGORIES = [c for c in poi_lib.CATEGORIES if c != "transport"]


class App:
    def __init__(self, store: RouteStore, services: Services):
        self.store = store
        self.services = services

    # --- Accès ------------------------------------------------------------------------

    def load(self, route_id: str) -> Route:
        # Seuls les messages de ToolError sont transmis à Claude : on traduit les erreurs prévues.
        try:
            return self.store.load(route_id)
        except (KeyError, ValueError) as exc:
            raise ToolError(exc.args[0]) from exc

    def save(self, route: Route) -> None:
        self.store.save(route)

    @staticmethod
    def external(call):
        try:
            return call()
        except (HttpError, ValueError, OSError) as exc:  # OSError : lecture raster (rasterio) ou fichier
            raise ToolError(str(exc)) from exc

    def overpass(self, query: str) -> list[dict]:
        return self.external(lambda: self.services.overpass.query(query))

    def refuges_near(self, route: Route, margin_m: float = 600) -> list[dict]:
        if not self.services.refuges:
            return []
        s, w, n, e = poi_lib.bbox_around(route.points, margin_m)
        if w > e:  # emprise à cheval sur l'antiméridien : hors couverture de refuges.info (Europe)
            return []
        return self.external(lambda: self.services.refuges.points(s, w, n, e))

    # --- Altimétrie et statistiques -------------------------------------------------------

    def elevations(self, points: list[tuple[float, float]]):
        return self.external(lambda: self.services.elevation.elevations(points))

    def apply_dem(self, route: Route) -> None:
        """Densifie le tracé et remplace ses altitudes par celles du MNT."""
        lats, lons = densify(
            np.array([p.lat for p in route.points]), np.array([p.lon for p in route.points]), DENSIFY_M
        )
        res = self.elevations(list(zip(lats.tolist(), lons.tolist(), strict=True)))
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
        notes += [f"Source d'altitude indisponible, source suivante utilisée : {e}" for e in res.errors]
        route.elevation_notes = notes

    def stats_into(
        self, route: Route, params: ElevationParams | None = None, profile: WalkerProfile | None = None
    ) -> None:
        stats, warnings = compute_stats(
            route.points,
            params or (route.stats.params if route.stats else None),
            profile or (route.stats.profile if route.stats else None),
            elevation_source=route.elevation_source,
        )
        route.stats, route.warnings = stats, route.elevation_notes + warnings
        route.validation = None  # les chiffres ont changé : la validation doit être relancée
        route.stages = None

    def make_route(
        self,
        wps: list[tuple[float, float]],
        required: list[tuple[float, float]],
        profile: str,
        request: RouteRequest,
        name: str,
        with_dem: bool = True,
    ) -> Route:
        """Tracé BRouter + altimétrie MNT + stats, non enregistré.
        `required` : points imposés par l'utilisateur (vérifiés par la règle G6)."""
        result = self.external(lambda: self.services.router.route(wps, profile))
        route = Route(
            route_id=new_route_id(),
            name=name,
            source=f"BRouter:{profile}",
            points=result.points,
            waypoints=required,
            request=request,
            segments=result.segments,
            engine_stats=result.engine_stats,
        )
        if with_dem:
            self.apply_dem(route)
            # Aller-retour imposé par un point au bout d'une impasse : signalé (notes gardées à chaque recalcul).
            route.elevation_notes = route.elevation_notes + loops.spur_notes(route.points, required)
            self.stats_into(route)
        return route

    # --- Analyses à la demande ------------------------------------------------------------

    def ensure_pois(self, route: Route, categories: list[str] | None = None, max_detour_m: float = 300.0) -> None:
        cats = list(categories or DEFAULT_CATEGORIES)
        bbox = poi_lib.bbox_around(route.points, max_detour_m + 50)
        elements = self.overpass(poi_lib.build_query(bbox, cats))
        route.pois = poi_lib.annotate(route.points, elements, cats, max_detour_m)
        route.validation = None

    def ensure_technical(self, route: Route) -> None:
        res = self.parallel(
            {
                "osm": lambda: self.overpass(technical_lib.build_query(route.points)),
                "refuges": lambda: self.refuges_near(route, 100),
            }
        )
        if isinstance(res["osm"], ToolError):
            raise res["osm"]
        elements = res["osm"]
        # refuges.info est un complément : son absence ne bloque pas l'analyse
        refuges = [] if isinstance(res["refuges"], ToolError) else res["refuges"]
        route.technical = technical_lib.technical_passages(
            route.points, route.segments, elements, route.engine_stats.get("distance_m"), refuges
        )
        route.validation = None

    def ensure_areas(self, route: Route) -> None:
        route.areas = areas_lib.crossings(route.points, self.overpass(areas_lib.build_query(route.points)))
        route.validation = None

    @staticmethod
    def parallel(calls: dict[str, Callable[[], object]]) -> dict[str, object]:
        """Exécute des appels indépendants en parallèle (chacun attend surtout un service externe) ;
        renvoie {nom: résultat, ou l'exception ToolError si l'appel a échoué}."""
        with ThreadPoolExecutor(max_workers=max(1, len(calls))) as pool:
            futures = {name: pool.submit(fn) for name, fn in calls.items()}
        out: dict[str, object] = {}
        for name, f in futures.items():
            try:
                out[name] = f.result()
            except ToolError as exc:
                out[name] = exc
        return out

    def run_missing_analyses(self, route: Route) -> list[str]:
        """Points notables, passages techniques et zones réglementées manquants, en parallèle.
        Une source indisponible ne bloque pas les autres ; renvoie la liste des analyses impossibles."""
        steps = (
            ("points notables", route.pois is None, self.ensure_pois),
            ("passages techniques", route.technical is None, self.ensure_technical),
            ("zones réglementées", route.areas is None, self.ensure_areas),
        )
        res = self.parallel({label: (lambda fn=fn: fn(route)) for label, missing, fn in steps if missing})
        return [f"{label} : {r}" for label, r in res.items() if isinstance(r, ToolError)]

    def validate_full(self, route: Route) -> list[str]:
        """Analyses manquantes puis validation ; renvoie les analyses impossibles."""
        failures = self.run_missing_analyses(route)
        route.validation = validate(route)
        return failures
