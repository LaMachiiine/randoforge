"""Analyses du terrain le long du tracé : pentes fortes, portions parcourues deux fois."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString

from .geo import LocalProjection, cumulative_distance, resample
from .models import TrackPoint

STEP_M = 10.0
MIN_RETRACE_SECTION_M = 30.0  # en dessous : simple croisement ou bruit de géométrie


@dataclass
class Section:
    start_m: float
    end_m: float
    value: float  # pente max (%) ou longueur, selon l'analyse


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Indices (début, fin inclusive) des suites de True."""
    idx = np.flatnonzero(mask)
    if not len(idx):
        return []
    groups = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
    return [(int(g[0]), int(g[-1])) for g in groups]


def steep_sections(points: list[TrackPoint], threshold_pct: float = 35.0, window_m: float = 100.0) -> list[Section]:
    """Portions où la pente moyenne sur `window_m` dépasse `threshold_pct` (montée ou descente)."""
    if any(p.ele is None for p in points) or len(points) < 2:
        return []
    lats = np.array([p.lat for p in points])
    lons = np.array([p.lon for p in points])
    eles = np.array([p.ele for p in points], dtype=float)
    dist, _, _, e = resample(lats, lons, eles, STEP_M)
    k = int(window_m / STEP_M)
    if len(e) <= k:
        return []
    slope = 100 * np.abs(e[k:] - e[:-k]) / window_m
    return [
        Section(float(dist[a]), float(dist[b + k]), float(slope[a : b + 1].max()))
        for a, b in _runs(slope > threshold_pct)
    ]


def retraced_sections(points: list[TrackPoint], tolerance_m: float = 12.0, min_gap_m: float = 300.0) -> list[Section]:
    """Portions où le tracé repasse sur un tronçon déjà parcouru (aller-retour).

    Un point est « repassé » s'il est à moins de `tolerance_m` d'un segment parcouru
    au moins `min_gap_m` plus tôt. Renvoie les portions repassées (seconde passe).
    """
    if len(points) < 3:
        return []
    lats = np.array([p.lat for p in points])
    lons = np.array([p.lon for p in points])
    cum = cumulative_distance(lats, lons)
    mid = len(points) // 2
    xs, ys = LocalProjection(lats[mid], lons[mid]).to_xy(lats, lons)
    coords = np.column_stack([xs, ys])
    segments = shapely.linestrings(np.stack([coords[:-1], coords[1:]], axis=1))
    pts = shapely.points(coords)
    tree = shapely.STRtree(segments)
    pi, si = tree.query(pts, predicate="dwithin", distance=tolerance_m)
    earlier = cum[pi] - cum[si + 1] >= min_gap_m
    mask = np.zeros(len(points), dtype=bool)
    mask[pi[earlier]] = True
    sections = [Section(float(cum[a]), float(cum[b]), float(cum[b] - cum[a])) for a, b in _runs(mask)]
    return [sec for sec in sections if sec.value >= MIN_RETRACE_SECTION_M]


def route_line(points: list[TrackPoint]) -> tuple[LineString, LocalProjection, np.ndarray]:
    """Tracé projeté en mètres + distance cumulée géodésique de chaque point."""
    lats = np.array([p.lat for p in points])
    lons = np.array([p.lon for p in points])
    mid = len(points) // 2
    proj = LocalProjection(lats[mid], lons[mid])
    xs, ys = proj.to_xy(lats, lons)
    return LineString(np.column_stack([xs, ys])), proj, cumulative_distance(lats, lons)
