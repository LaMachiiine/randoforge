"""Outils de construction de tracés : point à point, boucles automatiques, import, repli."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..app import App
from ..core import loops
from ..core.geo import cumulative_distance
from ..core.models import Route, RouteRequest, RouteSummary
from ..core.quality import marked_share
from ..core.similarity import overlap_fraction
from ..core.terrain import retraced_sections
from ..formats.gpx import read_gpx
from ..storage import new_route_id
from ..validation import tarmac_length
from .schemas import LatLon, LoopCandidate, LoopCandidates, Profile, SacScale

COMPASS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def done_overlap(app: App, route: Route) -> float:
    done = [r for r in app.store.list() if r.done_on and r.route_id != route.route_id]
    return max((overlap_fraction(route.points, d.points) for d in done), default=0.0)


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def route_between(
        waypoints: Annotated[list[LatLon], Field(min_length=2, max_length=30)],
        profile: Profile = "hiking-mountain",
        loop: bool = False,
        name: str | None = None,
        max_sac_scale: SacScale | None = None,
    ) -> RouteSummary:
        """Calcule un tracé sur de vrais chemins passant par les points donnés, dans l'ordre.

        - `loop=True` : revient au premier point (boucle). Pour une boucle via un lieu imposé
          (cascade, sommet), donner départ + lieu(x) avec loop=True.
        - `max_sac_scale` : difficulté maximale acceptée (hiking = T1 facile … alpine_hiking = T4).
        Jusqu'à 30 points : suffisant pour une itinérance de plusieurs jours.
        Distance et dénivelé sont recalculés sur un MNT précis (IGN en France, Copernicus ailleurs).
        """
        required = [(w.lat, w.lon) for w in waypoints]
        wps = required + [required[0]] if loop and required[0] != required[-1] else list(required)
        route = app.make_route(
            wps,
            required,
            profile,
            RouteRequest(loop=loop, max_sac_scale=max_sac_scale),
            name or f"Itinéraire {profile}",
        )
        app.save(route)
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
        avoid_done: bool = True,
        name: str | None = None,
    ) -> LoopCandidates:
        """Génère automatiquement des boucles depuis un départ pour une distance (et un D+) cible,
        dans plusieurs directions, et renvoie les `n` meilleures, déjà mesurées sur le MNT.

        Classement : écart à la distance et au D+ demandés, pénalité pour les allers-retours et le
        goudron, bonus pour les sentiers balisés ; `avoid_done` pénalise les boucles qui reprennent
        des randos marquées comme faites (mark_done). Prévoir ~20–40 s.
        """
        origin = (start.lat, start.lon)
        target_m = distance_km * 1000
        request = RouteRequest(
            loop=True, max_sac_scale=max_sac_scale, target_distance_km=distance_km, target_d_plus_m=d_plus_m
        )
        tried = failed = 0
        drafts: list[tuple[float, Route, float, float]] = []  # (direction, tracé, aller-retour m, goudron m)
        for bearing in loops.bearings(directions):
            radius = loops.initial_radius(target_m)
            best: Route | None = None
            for _ in range(2):  # un essai + une correction de taille
                tried += 1
                try:
                    draft = app.make_route(
                        loops.triangle(origin, bearing, radius),
                        [origin],
                        profile,
                        request.model_copy(),
                        "",
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

        def extra(r: Route) -> tuple[float, float]:
            marked = (marked_share(r.segments) or 0) / 100
            return marked, done_overlap(app, r) if avoid_done else 0.0

        def pre_score(d) -> float:
            _, r, retrace, tarmac = d
            return loops.score(r.engine_stats["distance_m"], target_m, None, None, retrace, tarmac, *extra(r)).total

        # Mesure fine (MNT) seulement pour les meilleurs brouillons : économise les appels d'altimétrie.
        scored = []
        for bearing, r, retrace, tarmac in sorted(drafts, key=pre_score)[: n + 2]:
            app.apply_dem(r)
            app.stats_into(r)
            marked, done = extra(r)
            sc = loops.score(
                r.stats.distance_km * 1000, target_m, r.stats.d_plus_m, d_plus_m, retrace, tarmac, marked, done
            )
            scored.append((sc.total, bearing, r, retrace, tarmac, marked, done))
        scored.sort(key=lambda x: x[0])

        candidates = []
        for i, (total, bearing, r, retrace, tarmac, marked, done) in enumerate(scored[:n], 1):
            r.name = f"{name or 'Boucle'} {i} ({COMPASS[round(bearing / 45) % 8]})"
            app.save(r)
            candidates.append(
                LoopCandidate(
                    route=RouteSummary.of(r),
                    bearing_deg=bearing,
                    retrace_km=round(retrace / 1000, 2),
                    tarmac_pct=round(100 * tarmac / max(1.0, r.engine_stats.get("distance_m", 0))),
                    balise_pct=round(100 * marked),
                    deja_fait_pct=round(100 * done),
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
        Lancer ensuite data_quality pour vérifier que la trace suit des chemins (règle G1).
        """
        file = Path(path).expanduser()
        if not file.is_file():
            raise ToolError(f"Fichier introuvable : {file}")
        gpx_name, points = read_gpx(file.read_text(encoding="utf-8"))
        if len(points) < 2:
            raise ToolError("Le GPX ne contient pas de trace exploitable (moins de 2 points).")
        route = Route(
            route_id=new_route_id(), name=name or gpx_name or file.stem, source=f"gpx:{file.name}", points=points
        )
        if elevation == "dem":
            app.apply_dem(route)
        else:
            route.elevation_source = "fichier GPX"
        app.stats_into(route)
        app.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def bailout_route(
        route_id: str,
        at_km: Annotated[float, Field(ge=0)],
        to: Literal["depart", "arrivee"] = "depart",
        target: LatLon | None = None,
        profile: Profile = "shortest",
    ) -> RouteSummary:
        """Itinéraire de repli : depuis le point situé à `at_km` sur le tracé, rejoindre au plus
        court le départ, l'arrivée, ou un lieu donné (`target` : parking, village, arrêt de bus).

        À proposer pour les passages exposés, la météo incertaine ou une fatigue imprévue.
        """
        route = app.load(route_id)
        if route.stats is None or at_km > route.stats.distance_km:
            raise ToolError(f"at_km doit être entre 0 et {route.stats.distance_km if route.stats else 0:.1f} km.")
        lats = np.array([p.lat for p in route.points])
        lons = np.array([p.lon for p in route.points])
        cum = cumulative_distance(lats, lons)
        here = (float(np.interp(at_km * 1000, cum, lats)), float(np.interp(at_km * 1000, cum, lons)))
        if target:
            goal, label = (target.lat, target.lon), "le lieu choisi"
        else:
            p = route.points[0] if to == "depart" else route.points[-1]
            goal, label = (p.lat, p.lon), "le départ" if to == "depart" else "l'arrivée"
        bail = app.make_route(
            [here, goal],
            [here, goal],
            profile,
            RouteRequest(),
            f"Repli depuis le km {at_km:.1f} de « {route.name} » vers {label}",
        )
        app.save(bail)
        return RouteSummary.of(bail)
