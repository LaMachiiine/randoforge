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


def unwrap_lons(lons) -> np.ndarray:
    """Longitudes rendues continues (pas de saut de 360° en traversant ±180°) : interpolables linéairement."""
    return np.degrees(np.unwrap(np.radians(np.asarray(lons, dtype=float))))


def wrap_lons(lons):
    """Ramène des longitudes dans [-180, 180[."""
    return (np.asarray(lons, dtype=float) + 180.0) % 360.0 - 180.0


def interp_lon(x, xp, lons):
    """`np.interp` pour des longitudes, correct de part et d'autre de l'antiméridien."""
    return wrap_lons(np.interp(x, xp, unwrap_lons(lons)))


def lon_bounds(lons, margin_deg: float = 0.0) -> tuple[float, float]:
    """(ouest, est) des longitudes ; ouest > est si l'emprise traverse l'antiméridien (convention Overpass)."""
    u = unwrap_lons(lons)
    w, e = float(u.min()) - margin_deg, float(u.max()) + margin_deg
    if e - w >= 360:
        return -180.0, 180.0
    ww = float(wrap_lons(w))
    ee = ww + (e - w)  # même largeur ; repasse en [-180, 180] seulement si l'emprise traverse l'antiméridien
    return ww, ee if ee <= 180.0 else float(wrap_lons(ee))


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
        interp_lon(grid, d, lons[keep]),
        np.interp(grid, d, eles[keep]),
    )


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance géodésique (m) entre deux points (lat, lon)."""
    _, _, dist = GEOD.inv(a[1], a[0], b[1], b[0])
    return float(dist)


def densify(lats: np.ndarray, lons: np.ndarray, max_step_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Ajoute des points intermédiaires pour qu'aucun segment ne dépasse `max_step_m`.

    Les points d'origine sont conservés (contrairement à `resample`), ce qui préserve
    les virages exacts du tracé.
    """
    lats, lons = np.asarray(lats, dtype=float), unwrap_lons(lons)
    if len(lats) < 2:
        return lats, wrap_lons(lons)
    # Vectorisé : n points par segment, positions fractionnaires (j+1)/n le long de chaque segment.
    n = np.maximum(1, np.ceil(segment_lengths(lats, wrap_lons(lons)) / max_step_m).astype(int))
    seg = np.repeat(np.arange(len(n)), n)
    t = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n) + 1) / n[seg]
    out_lat = np.concatenate([lats[:1], lats[seg] + (lats[seg + 1] - lats[seg]) * t])
    out_lon = np.concatenate([lons[:1], lons[seg] + (lons[seg + 1] - lons[seg]) * t])
    return out_lat, wrap_lons(out_lon)


class LocalProjection:
    """Projection azimutale équidistante centrée sur la zone : coordonnées en mètres,
    distances fidèles (< 0,1 %) dans un rayon de quelques dizaines de km. Sert aux calculs shapely.
    """

    def __init__(self, lat0: float, lon0: float):
        from pyproj import Transformer

        crs = f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m"
        self._fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        self._inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    def to_xy(self, lats, lons):
        return self._fwd.transform(lons, lats)

    def to_latlon(self, xs, ys):
        lons, lats = self._inv.transform(xs, ys)
        return lats, lons


def destination_points(lat: float, lon: float, bearings_deg: list[float], dist_m: float) -> list[tuple[float, float]]:
    """Points à `dist_m` du point donné, dans chacune des directions (0 = nord)."""
    lons2, lats2, _ = GEOD.fwd(
        [lon] * len(bearings_deg), [lat] * len(bearings_deg), bearings_deg, [dist_m] * len(bearings_deg)
    )
    return list(zip(lats2, lons2, strict=True))
