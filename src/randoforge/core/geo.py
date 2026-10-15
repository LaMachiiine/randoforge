"""Calculs géodésiques sur l'ellipsoïde WGS84."""

from __future__ import annotations

import numpy as np
from pyproj import Geod

GEOD = Geod(ellps="WGS84")


def segment_lengths(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Longueur géodésique (m) de chaque segment entre points consécutifs."""
    if len(lats) < 2:
        return np.zeros(0)
    _, _, dist = GEOD.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])
    return np.asarray(dist, dtype=float)


def cumulative_distance(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Distance cumulée (m) depuis le premier point ; même longueur que l'entrée."""
    return np.concatenate([[0.0], np.cumsum(segment_lengths(lats, lons))])


def resample(
    lats: np.ndarray, lons: np.ndarray, eles: np.ndarray, step_m: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Rééchantillonne le tracé à pas fixe le long de la distance cumulée.

    L'interpolation lat/lon est linéaire entre points d'origine : l'erreur est négligeable
    pour des segments de randonnée (quelques dizaines de mètres). Le dernier point est
    toujours conservé. Renvoie (dist, lats, lons, eles).
    """
    dist = cumulative_distance(lats, lons)
    total = dist[-1]
    grid = np.arange(0.0, total, step_m)
    grid = np.append(grid, total)
    # np.interp exige des abscisses croissantes : les points dupliqués (distance nulle) sont retirés.
    keep = np.concatenate([[True], np.diff(dist) > 0])
    d = dist[keep]
    return (
        grid,
        np.interp(grid, d, lats[keep]),
        np.interp(grid, d, lons[keep]),
        np.interp(grid, d, eles[keep]),
    )


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance géodésique (m) entre deux points (lat, lon)."""
    _, _, dist = GEOD.inv(a[1], a[0], b[1], b[0])
    return float(dist)
