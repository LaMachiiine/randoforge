"""Comparaison géométrique de tracés : écart à une trace de référence, recouvrement avec des randos déjà faites."""

from __future__ import annotations

import numpy as np
import shapely
from pydantic import BaseModel
from shapely.geometry import LineString

from .geo import LocalProjection, cumulative_distance
from .models import TrackPoint


class ReferenceComparison(BaseModel):
    ecart_moyen_m: float
    ecart_max_m: float
    part_a_moins_25m_pct: float
    distance_km: float | None
    distance_ref_km: float | None
    ecart_distance_pct: float | None
    ecart_distance_km: float | None = None
    d_plus_m: int | None
    d_plus_ref_m: int | None
    ecart_d_plus_pct: float | None
    ecart_d_plus_m: int | None = None


def _xy(points: list[TrackPoint], proj: LocalProjection) -> np.ndarray:
    xs, ys = proj.to_xy(np.array([p.lat for p in points]), np.array([p.lon for p in points]))
    return np.column_stack([xs, ys])


def deviation(route: list[TrackPoint], reference: list[TrackPoint]) -> tuple[float, float, float]:
    """(écart moyen, écart max, % de points du tracé à moins de 25 m de la référence)."""
    mid = route[len(route) // 2]
    proj = LocalProjection(mid.lat, mid.lon)
    ref = _xy(reference, proj)
    # Index spatial des segments de la référence : distance exacte au plus proche, sans tester tous les segments.
    tree = shapely.STRtree(shapely.linestrings(np.stack([ref[:-1], ref[1:]], axis=1)))
    _, d = tree.query_nearest(shapely.points(_xy(route, proj)), return_distance=True, all_matches=False)
    return float(d.mean()), float(d.max()), float(100 * (d <= 25).mean())


def overlap_fraction(route: list[TrackPoint], other: list[TrackPoint], tolerance_m: float = 25.0) -> float:
    """Part (en longueur) du tracé située à moins de `tolerance_m` d'un autre tracé."""
    if len(route) < 2 or len(other) < 2:
        return 0.0
    mid = route[len(route) // 2]
    proj = LocalProjection(mid.lat, mid.lon)
    line = LineString(_xy(other, proj))
    shapely.prepare(line)  # test « à moins de » préparé : ~25× plus rapide que distance() sur 8 000 points
    near = shapely.dwithin(line, shapely.points(_xy(route, proj)), tolerance_m)
    seg = np.diff(cumulative_distance(np.array([p.lat for p in route]), np.array([p.lon for p in route])))
    covered = seg[near[:-1] & near[1:]].sum()
    return float(covered / seg.sum()) if seg.sum() else 0.0


def pct(a: float | None, b: float | None) -> float | None:
    return round(100 * (a - b) / b, 1) if a is not None and b else None
