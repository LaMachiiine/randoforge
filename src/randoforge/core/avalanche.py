"""Terrain avalancheux le long d'un tracé, calculé sur le relief (pas un bulletin de risque).

Deux expositions, à partir d'une grille d'altitudes (calcul pur, la grille est passée en paramètre) :
- **pente traversée** : le sentier passe lui-même sur une pente de 30° ou plus (zone de départ possible) ;
- **pente au-dessus** : une pente de départ possible (30° à 55°) domine le sentier dans un rayon de 500 m, assez
  haut pour qu'une avalanche puisse l'atteindre (angle de portée ≥ 22° entre le sentier et le haut de la pente).
Méthode et sources des seuils : docs/10 - Architecture/Terrain avalancheux.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

RELEASE_MIN_DEG = 30.0  # sous 30°, une plaque déclenche rarement (seuil classique, ATES, ANENA)
RELEASE_MAX_DEG = 55.0  # au-delà, la neige purge en continu (peu de grosses accumulations)
STEEP_DEG = (30.0, 35.0, 40.0)  # paliers annoncés pour la pente traversée
REACH_ANGLE_DEG = 22.0  # angle de portée minimal (« alpha angle ») : en deçà, une avalanche s'arrête avant
REACH_RADIUS_M = 500.0  # pentes prises en compte au-dessus du sentier
MIN_RELEASE_CELLS = 4  # pente de départ d'au moins ~0,3 ha (4 mailles de 30 m) : un talus ne compte pas
SAMPLE_M = 50.0
MIN_SECTION_M = 100.0  # tronçon signalé à partir de 100 m


@dataclass
class Grid:
    """Grille d'altitudes en degrés : ligne 0 = bord nord, NaN hors données."""

    z: np.ndarray
    top: float
    left: float
    dlat: float
    dlon: float


@dataclass
class Section:
    """Tronçon exposé : pente traversée et/ou pente de départ au-dessus (0 si absente)."""

    start_m: float
    end_m: float
    cross_deg: float  # pente la plus raide sous le sentier (≥ 30°), sinon 0
    above_deg: float  # pente de départ la plus raide qui peut atteindre le sentier, sinon 0
    above_m: float  # sa hauteur au-dessus du sentier


SNOW_MARGIN_KM = 0.2  # tolérance de chevauchement avec un tronçon enneigé (échantillonnage des deux calculs)


def snowy(sec: Section, snow_km: list[tuple[float, float]], line_m: float | None, trail_top_m: float | None) -> bool:
    """Vrai si la neige est probable sur ce tronçon exposé : il chevauche un tronçon enneigé du tracé, ou le haut de
    la pente de départ au-dessus de lui dépasse la limite de la neige (la neige peut partir d'au-dessus du sentier)."""
    a, b = sec.start_m / 1000, sec.end_m / 1000
    if any(lo - SNOW_MARGIN_KM <= b and a <= hi + SNOW_MARGIN_KM for lo, hi in snow_km):
        return True
    return line_m is not None and trail_top_m is not None and trail_top_m + sec.above_m >= line_m


def slope_deg(g: Grid) -> np.ndarray:
    """Pente (degrés) de chaque maille, mailles en mètres selon la latitude."""
    lat = g.top - (np.arange(g.z.shape[0]) + 0.5) * g.dlat
    dy = g.dlat * 111_320.0
    dx = (g.dlon * 111_320.0 * np.cos(np.radians(lat)))[:, None]
    gy, gx = np.gradient(g.z, dy, axis=0), np.gradient(g.z, axis=1) / dx
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def exposure(
    g: Grid, lats: np.ndarray, lons: np.ndarray, eles: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pour chaque point : pente sous le sentier (°), pente de départ la plus raide qui peut l'atteindre (°, 0 si
    aucune) et sa hauteur au-dessus du sentier (m)."""
    slope = slope_deg(g)
    release = (slope >= RELEASE_MIN_DEG) & (slope <= RELEASE_MAX_DEG)
    rows = ((g.top - lats) / g.dlat).astype(int)
    cols = ((lons - g.left) / g.dlon).astype(int)
    lat0 = float(np.mean(lats))
    cell_y, cell_x = g.dlat * 111_320.0, g.dlon * 111_320.0 * math.cos(math.radians(lat0))
    ry, rx = int(REACH_RADIUS_M / cell_y) + 1, int(REACH_RADIUS_M / cell_x) + 1
    oy, ox = np.mgrid[-ry : ry + 1, -rx : rx + 1]
    dist = np.hypot(oy * cell_y, ox * cell_x)
    disk = (dist <= REACH_RADIUS_M) & (dist > 0)
    under = np.zeros(len(lats))
    reach_slope = np.zeros(len(lats))
    reach_height = np.zeros(len(lats))
    h, w = g.z.shape
    for k, (r, c, ele) in enumerate(zip(rows, cols, eles, strict=True)):
        if not (0 <= r < h and 0 <= c < w):
            continue
        under[k] = np.nanmax(slope[max(0, r - 1) : r + 2, max(0, c - 1) : c + 2])
        if np.isnan(ele):
            ele = g.z[r, c]
        r0, r1, c0, c1 = r - ry, r + ry + 1, c - rx, c + rx + 1
        if r0 < 0 or c0 < 0 or r1 > h or c1 > w:
            continue  # bord de la grille : la marge autour du tracé l'évite
        zz, rel = g.z[r0:r1, c0:c1], release[r0:r1, c0:c1] & disk
        rise = zz - ele
        reach = rel & (rise > 0) & (np.degrees(np.arctan2(rise, dist)) >= REACH_ANGLE_DEG)
        if reach.sum() >= MIN_RELEASE_CELLS:
            reach_slope[k] = float(np.nanmax(slope[r0:r1, c0:c1][reach]))
            reach_height[k] = float(np.nanmax(rise[reach]))
    return under, reach_slope, reach_height


def sections(cum_m: np.ndarray, under: np.ndarray, reach_slope: np.ndarray, reach_height: np.ndarray) -> list[Section]:
    """Tronçons exposés (pente ≥ 30° sous le sentier, ou pente de départ au-dessus) ; deux tronçons séparés de
    moins de 100 m n'en font qu'un."""
    exposed = (under >= RELEASE_MIN_DEG) | (reach_slope > 0)
    idx = np.flatnonzero(exposed)
    if not len(idx):
        return []
    gap = np.diff(cum_m[idx]) > MIN_SECTION_M  # coupure si plus de 100 m entre deux points exposés
    out: list[Section] = []
    for run in np.split(idx, np.flatnonzero(gap) + 1):
        a, b = cum_m[run[0]], cum_m[min(run[-1] + 1, len(cum_m) - 1)]
        if b - a < MIN_SECTION_M:
            continue
        cross = under[run][under[run] >= RELEASE_MIN_DEG]
        out.append(Section(float(a), float(b), float(cross.max()) if len(cross) else 0.0,
                           float(reach_slope[run].max()), float(reach_height[run].max())))  # fmt: skip
    return out
