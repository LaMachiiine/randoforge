"""Règles de validation d'un itinéraire (docs/10 - Architecture/Validation & cohérence.md).

Chaque règle renvoie des `Check`. Les identifiants correspondent à la documentation.
Une règle qui ne peut pas être vérifiée faute de données le dit (niveau `info`)
plutôt que de se taire.
"""

from __future__ import annotations

import numpy as np

from .core.geo import distance_m, resample, segment_lengths
from .core.models import SAC_SCALE, Check, Route, ValidationReport
from .core.stats import LOOP_TOLERANCE_M

GAP_M = 100.0
WAYPOINT_TOL_M = 50.0
STEEP_PCT = 35.0
STEEP_LEN_M = 100.0
TARMAC_HIGHWAYS = {
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "trunk",
    "living_street",
}
PAVED = {"asphalt", "paved", "concrete", "concrete:plates", "paving_stones", "sett"}
BUSY_ROADS = {"trunk", "primary", "secondary"}
BUSY_MIN_M = 100.0


def _km(m: float) -> float:
    return round(m / 1000, 2)


def check_geometry(route: Route) -> list[Check]:
    checks = []
    lats = np.array([p.lat for p in route.points])
    lons = np.array([p.lon for p in route.points])
    seg = segment_lengths(lats, lons)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    for i in np.flatnonzero(seg > GAP_M)[:5]:
        checks.append(
            Check(
                id="G2",
                level="error",
                km=_km(cum[i]),
                message=f"Saut de {seg[i]:.0f} m sans géométrie entre deux points",
            )
        )

    start, end = (route.points[0].lat, route.points[0].lon), (route.points[-1].lat, route.points[-1].lon)
    if route.request.loop and distance_m(start, end) > LOOP_TOLERANCE_M:
        checks.append(
            Check(
                id="G3",
                level="error",
                message=f"Boucle demandée mais l'arrivée est à {distance_m(start, end):.0f} m du départ",
            )
        )

    for n, wp in enumerate(route.waypoints, 1):
        d = min(distance_m(wp, (p.lat, p.lon)) for p in route.points)
        if d > WAYPOINT_TOL_M:
            checks.append(
                Check(
                    id="G6",
                    level="error",
                    message=f"Point de passage n°{n} non atteint : le tracé passe à {d:.0f} m",
                    suggestion="Déplacer ce point sur un chemin (ou vérifier qu'un chemin y mène).",
                )
            )
    return checks


def check_ways(route: Route) -> list[Check]:
    if not route.segments:
        return [
            Check(
                id="A1",
                level="info",
                message="Pas de données sur les chemins empruntés (trace importée) : accès et difficulté non vérifiés",
            )
        ]
    checks = []
    total = route.segments[-1].end_m or 1
    tarmac = 0.0
    busy: list[list] = []
    no_sac_path = 0.0
    max_sac = route.request.max_sac_scale
    for s in route.segments:
        t = s.tags
        length = s.end_m - s.start_m
        if t.get("access") in {"no", "private"} or t.get("foot") in {"no", "private"}:
            checks.append(
                Check(
                    id="A1",
                    level="error",
                    km=_km(s.start_m),
                    message=f"Passage interdit aux piétons ou privé ({length:.0f} m)",
                )
            )
        if t.get("highway") in BUSY_ROADS:
            # Portions consécutives regroupées : une simple traversée de route n'est pas signalée.
            if busy and busy[-1][1] == s.start_m:
                busy[-1][1] = s.end_m
            else:
                busy.append([s.start_m, s.end_m, t["highway"]])
        if t.get("highway") in TARMAC_HIGHWAYS or t.get("surface") in PAVED:
            tarmac += length
        if t.get("highway") == "path" and "sac_scale" not in t:
            no_sac_path += length
        sac = t.get("sac_scale")
        if max_sac and sac in SAC_SCALE and SAC_SCALE.index(sac) > SAC_SCALE.index(max_sac):
            checks.append(
                Check(
                    id="D1",
                    level="error",
                    km=_km(s.start_m),
                    message=f"Difficulté {sac} sur {length:.0f} m, au-delà du maximum demandé ({max_sac})",
                    suggestion="Recalculer avec un autre point de passage pour contourner ce passage.",
                )
            )
    for start, end, kind in busy:
        if end - start >= BUSY_MIN_M:
            checks.append(
                Check(
                    id="A4",
                    level="warning",
                    km=_km(start),
                    message=f"{end - start:.0f} m sur une route fréquentée ({kind})",
                )
            )
    pct = 100 * tarmac / total
    if pct > route.request.max_tarmac_pct:
        checks.append(
            Check(
                id="A5",
                level="warning",
                message=f"{pct:.0f} % du parcours sur route goudronnée "
                f"(max souhaité {route.request.max_tarmac_pct:.0f} %)",
            )
        )
    if no_sac_path > 500 and route.stats and (route.stats.alt_max_m or 0) > 1000:
        checks.append(
            Check(
                id="Q1",
                level="info",
                message=f"{no_sac_path / 1000:.1f} km de sentiers sans difficulté renseignée dans OSM : "
                "difficulté incertaine",
            )
        )
    return checks


def check_numbers(route: Route) -> list[Check]:
    s = route.stats
    if s is None or s.d_plus_m is None:
        return [Check(id="N0", level="error", message="Altitudes manquantes : dénivelé non calculé")]
    checks = []
    if s.is_loop and max(s.d_plus_m, s.d_minus_m) > 0:
        gap = abs(s.d_plus_m - s.d_minus_m) / max(s.d_plus_m, s.d_minus_m)
        if gap > 0.01:
            checks.append(
                Check(
                    id="N1",
                    level="error",
                    message=f"Boucle avec D+ {s.d_plus_m:.0f} m ≠ D- {s.d_minus_m:.0f} m",
                )
            )
    start_ele = route.points[0].ele
    # Tolérance = seuil d'hystérésis : une montée inférieure au seuil n'est pas comptée.
    if (
        start_ele is not None
        and s.alt_max_m is not None
        and s.d_plus_m + s.params.threshold_m < s.alt_max_m - start_ele - 1
    ):
        checks.append(
            Check(id="N3", level="error", message="D+ inférieur à l'écart entre le départ et le point culminant")
        )

    engine_dplus = route.engine_stats.get("d_plus_m")
    if engine_dplus:
        diff = abs(s.d_plus_m - engine_dplus)
        if diff > max(30, 0.15 * engine_dplus):
            checks.append(
                Check(
                    id="N5",
                    level="warning",
                    message=f"D+ calculé {s.d_plus_m:.0f} m vs {engine_dplus:.0f} m selon le moteur de routage "
                    "(MNT différents)",
                    suggestion="Notre valeur (MNT plus précis) fait foi ; l'écart signale une zone à vérifier.",
                )
            )
    return checks


def check_slopes(route: Route) -> list[Check]:
    if any(p.ele is None for p in route.points):
        return []
    lats = np.array([p.lat for p in route.points])
    lons = np.array([p.lon for p in route.points])
    eles = np.array([p.ele for p in route.points], dtype=float)
    dist, _, _, e = resample(lats, lons, eles, 10.0)
    k = int(STEEP_LEN_M / 10)
    if len(e) <= k:
        return []
    slope = 100 * np.abs(e[k:] - e[:-k]) / STEEP_LEN_M
    checks = []
    steep = np.flatnonzero(slope > STEEP_PCT)
    # Regroupe les fenêtres raides consécutives en passages
    if len(steep):
        groups = np.split(steep, np.flatnonzero(np.diff(steep) > 1) + 1)
        for g in groups[:5]:
            pct = slope[g].max()
            checks.append(
                Check(
                    id="D2",
                    level="warning",
                    km=_km(dist[g[0]]),
                    message=f"Passage raide : jusqu'à {pct:.0f} % sur ~{(len(g) + k) * 10} m",
                )
            )
    return checks


def check_pois(route: Route) -> list[Check]:
    if route.pois is None:
        return [
            Check(
                id="D7",
                level="info",
                message="Franchissements de cours d'eau non vérifiés (lancer annotate_route)",
            )
        ]
    return [
        Check(
            id="D7",
            level="warning",
            km=p.km,
            message=f"Gué{' sur ' + p.nom if p.nom else ''} : vérifier le niveau d'eau (crue, fonte des neiges)",
        )
        for p in route.pois
        if p.via == "gué"
    ]


def validate(route: Route) -> ValidationReport:
    checks = check_geometry(route) + check_ways(route) + check_numbers(route) + check_slopes(route) + check_pois(route)
    levels = {c.level for c in checks}
    status = "error" if "error" in levels else "warning" if "warning" in levels else "ok"
    return ValidationReport(status=status, checks=sorted(checks, key=lambda c: (c.km is None, c.km or 0)))
