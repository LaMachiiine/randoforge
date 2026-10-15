"""Contexte partagé par les outils MCP : stockage, services externes, opérations communes."""

from __future__ import annotations

import numpy as np
from mcp.server.mcpserver.exceptions import ToolError

from .core import areas as areas_lib
from .core import pois as poi_lib
from .core import technical as technical_lib
from .core.geo import densify
from .core.models import ElevationParams, Route, RouteRequest, TrackPoint, WalkerProfile
from .core.stats import compute_stats
from .engines.elevation import CopernicusElevation
from .http import HttpError
from .services import Services
from .storage import RouteStore, new_route_id

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
        except (HttpError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    def overpass(self, query: str) -> list[dict]:
        return self.external(lambda: self.services.overpass.query(query))

    def refuges_near(self, route: Route, margin_m: float = 600) -> list[dict]:
        if not self.services.refuges:
            return []
        s, w, n, e = poi_lib.bbox_around(route.points, margin_m)
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
        elements = self.overpass(technical_lib.build_query(route.points))
        try:
            refuges = self.refuges_near(route, 100)
        except ToolError:
            refuges = []  # refuges.info est un complément : son absence ne bloque pas l'analyse
        route.technical = technical_lib.technical_passages(
            route.points, route.segments, elements, route.engine_stats.get("distance_m"), refuges
        )
        route.validation = None

    def ensure_areas(self, route: Route) -> None:
        route.areas = areas_lib.crossings(route.points, self.overpass(areas_lib.build_query(route.points)))
        route.validation = None

    def best_effort(self, route: Route, *steps) -> list[str]:
        """Lance les analyses manquantes ; une source indisponible ne bloque pas les autres."""
        failures = []
        for missing, step, label in steps:
            if missing:
                try:
                    step(route)
                except ToolError as exc:
                    failures.append(f"{label} : {exc}")
        return failures
