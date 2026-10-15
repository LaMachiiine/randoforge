"""Découpage d'un itinéraire en étapes (rando sur plusieurs jours).

Programmation dynamique sur les points de coupure possibles (hébergements, bivouacs) :
on minimise l'écart des durées journalières à la cible, sous contrainte de durée max par jour,
en évitant de finir une étape par un passage technique.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .elevation import elevation_gain, median_smooth
from .geo import resample
from .models import ElevationParams, Poi, Stage, TechnicalPassage, TrackPoint, WalkerProfile
from .timing import estimate_minutes, format_duration

KIND_COST = {
    "refuge gardé": 0.0,
    "gîte": 0.0,
    "refuge": 0.05,
    "cabane": 0.1,
    "aire de bivouac / camping": 0.1,
    "camping": 0.1,
    "emplacement de bivouac": 0.15,
    "abri": 0.2,
    "emplacement possible": 0.3,
}
HOSTED = {"refuge gardé", "gîte", "refuge", "camping"}
TECH_END_PENALTY = 0.5


@dataclass
class Cut:
    m: float
    label: str
    kind: str


class Profile:
    """Profil altimétrique précalculé : D+/D- de n'importe quelle portion en O(1)."""

    def __init__(self, points: list[TrackPoint], params: ElevationParams):
        lats = np.array([p.lat for p in points])
        lons = np.array([p.lon for p in points])
        eles = np.array([p.ele for p in points], dtype=float)
        self.dist, _, _, e = resample(lats, lons, eles, params.step_m)
        e = median_smooth(e, int(round(params.smooth_window_m / params.step_m)))
        diff = np.diff(e)
        up_raw = np.concatenate([[0.0], np.cumsum(np.clip(diff, 0, None))])
        down_raw = np.concatenate([[0.0], np.cumsum(np.clip(-diff, 0, None))])
        # Les sommes brutes surestiment un peu (pas d'hystérésis) : on les recale sur le total exact.
        up, down = elevation_gain(e, params.threshold_m)
        self.up = up_raw * (up / up_raw[-1] if up_raw[-1] else 0)
        self.down = down_raw * (down / down_raw[-1] if down_raw[-1] else 0)
        self.total = float(self.dist[-1])

    def between(self, a: float, b: float) -> tuple[float, float, float]:
        ia, ib = np.searchsorted(self.dist, [a, b])
        ib = min(ib, len(self.dist) - 1)
        return b - a, float(self.up[ib] - self.up[ia]), float(self.down[ib] - self.down[ia])


def plan(
    points: list[TrackPoint],
    params: ElevationParams,
    walker: WalkerProfile,
    cuts: list[Cut],
    days: int | None,
    max_hours: float | None,
    technical: list[TechnicalPassage],
    pois: list[Poi],
) -> tuple[list[Stage], list[str]]:
    prof = Profile(points, params)
    nodes = (
        [Cut(0.0, "Départ", "départ")]
        + sorted((c for c in cuts if 200 < c.m < prof.total - 200), key=lambda c: c.m)
        + [Cut(prof.total, "Arrivée", "arrivée")]
    )
    n = len(nodes)

    def hours(i: int, j: int) -> float:
        d, up, down = prof.between(nodes[i].m, nodes[j].m)
        return estimate_minutes(d / 1000, up, down, walker) / 60

    total_h = hours(0, n - 1)
    max_h = max_hours or math.inf
    notes: list[str] = []

    def solve(k_days: int) -> list[int] | None:
        target = total_h / k_days
        inf = math.inf
        cost = [[inf] * n for _ in range(k_days + 1)]
        prev = [[-1] * n for _ in range(k_days + 1)]
        cost[0][0] = 0.0
        for k in range(1, k_days + 1):
            for j in range(1, n):
                if (k == k_days) != (j == n - 1):
                    continue  # la dernière étape finit à l'arrivée, les autres sur un hébergement
                for i in range(j):
                    if cost[k - 1][i] == inf:
                        continue
                    h = hours(i, j)
                    if h > max_h:
                        continue
                    c = cost[k - 1][i] + (h - target) ** 2 + KIND_COST.get(nodes[j].kind, 0.0)
                    end_m = nodes[j].m
                    span = end_m - nodes[i].m
                    if any(end_m - 0.2 * span <= t.km * 1000 <= end_m for t in technical) and j != n - 1:
                        c += TECH_END_PENALTY
                    if c < cost[k][j]:
                        cost[k][j], prev[k][j] = c, i
        if cost[k_days][n - 1] == math.inf:
            return None
        path, j = [n - 1], n - 1
        for k in range(k_days, 0, -1):
            j = prev[k][j]
            path.append(j)
        return path[::-1]

    if days:
        path = solve(days)
        if path is None:
            raise ValueError(
                f"Impossible de découper en {days} jours"
                + (f" avec au plus {max_hours:g} h par jour" if max_hours else "")
                + " : pas assez d'hébergements ou de bivouacs bien placés. Essayer find_bivouac_spots "
                "ou un autre nombre de jours."
            )
    else:
        if not max_hours:
            raise ValueError("Indiquer un nombre de jours ou une durée maximale par jour.")
        path = None
        for k in range(max(1, math.ceil(total_h / max_hours)), n):
            path = solve(k)
            if path:
                break
        if path is None:
            raise ValueError(f"Aucun découpage ne respecte {max_hours:g} h par jour avec les hébergements connus.")

    stages = []
    waters = [
        p for p in pois if p.categorie in {"eau", "lac", "cascade"} or (p.categorie == "riviere" and not p.intermittent)
    ]
    for day, (i, j) in enumerate(zip(path, path[1:], strict=False), 1):
        a, b = nodes[i].m, nodes[j].m
        d, up, down = prof.between(a, b)
        minutes = estimate_minutes(d / 1000, up, down, walker)
        tech = [f"km {t.km:.1f} : {', '.join(t.types)}" for t in technical if a <= t.km * 1000 <= b]
        stages.append(
            Stage(
                jour=day,
                km_debut=round(a / 1000, 2),
                km_fin=round(b / 1000, 2),
                distance_km=round(d / 1000, 2),
                d_plus_m=round(up),
                d_minus_m=round(down),
                duree_min=minutes,
                duree=format_duration(minutes),
                arrivee=nodes[j].label,
                arrivee_type=nodes[j].kind,
                passages_techniques=tech,
                points_eau=sum(1 for p in waters if a / 1000 <= p.km <= b / 1000),
            )
        )
    for s in stages[:-1]:
        if s.arrivee_type not in HOSTED:
            notes.append(
                f"Jour {s.jour} : nuit en {s.arrivee_type} ({s.arrivee}) — prévoir tente/duvet et vérifier la réglementation."
            )
        if s.points_eau == 0:
            notes.append(f"Jour {s.jour} : aucun point d'eau connu sur l'étape, prévoir l'eau de la journée.")
    spread = [s.duree_min for s in stages]
    if len(spread) > 1 and max(spread) - min(spread) > 120:
        notes.append("Étapes de durées inégales : les hébergements disponibles imposent ce découpage.")
    return stages, notes
