"""Enneigement le long d'un tracé : saison, limite de la neige, état par tronçon et durée ajustée.

Calculs purs : les observations (satellites) et le modèle (épaisseur, neige fraîche) sont passés en paramètre.
Méthode et sources des facteurs : docs/10 - Architecture/Neige.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .models import TrackPoint, WalkerProfile
from .timing import estimate_minutes

SNOW_NDSI = 40  # NDSI ≥ 0,40 : neige (seuil MODIS classique) ; 10..39 : neige partielle
PARTIAL_NDSI = 10
BAND_M = 100  # tranches d'altitude pour la limite de la neige
MIN_BAND_PX = 3  # pixels visibles minimum pour juger une tranche
FRESH_CM = 5  # neige tombée sur 72 h au-delà de laquelle elle est « fraîche » (non tassée)
SEASON_MIN_ALT_M = 600  # en saison froide, en dessous : pas d'analyse
SUMMER_MIN_ALT_M = 2000  # hors saison froide, analyse seulement au-dessus (névés, haute montagne)

# Facteurs de durée (temps « été » × facteur), à pied / en raquettes. Sources dans Neige.md :
# Suisse Rando/OFROU (×1,25 chemin hivernal damé, ×1,5 itinéraire raquettes), Pandolf/Soule & Goldman
# (coût énergétique dans la neige molle de 15/25/35 cm), Connolly 2002 (raquettes, neige tassée ou non),
# US Army ATP 3-90.97 (vitesses dans la neige non tracée). Valeurs prudentes (haut des fourchettes).
FACTORS = [  # (épaisseur max cm, fraîche ?, à pied, raquettes)
    (10, None, 1.25, 1.25),  # neige peu épaisse ou tassée
    (20, True, 1.5, 1.4),
    (40, True, 2.0, 1.7),
    (None, True, 3.0, 2.2),
    (None, False, 1.5, 1.4),  # neige ancienne épaisse (non damée) : comme une fraîche peu épaisse
]


def in_season(day: date, lat: float, alt_max_m: float) -> bool:
    """Saison froide (oct.–juin dans l'hémisphère nord, avr.–déc. au sud) au-dessus de 600 m, ou toute l'année
    au-dessus de 2 000 m."""
    month = day.month if lat >= 0 else (day.month + 5) % 12 + 1  # mois « équivalent nord »
    cold = month >= 10 or month <= 6
    return alt_max_m >= (SEASON_MIN_ALT_M if cold else SUMMER_MIN_ALT_M)


def snow_line(elevations: np.ndarray, values: np.ndarray) -> tuple[float | None, float, float]:
    """Limite de la neige d'après des pixels (altitude, NDSI ou nuage/inconnu < 0).

    Renvoie (limite en m ou None, plus basse altitude visible, plus haute) : la limite est le bas de la tranche
    de 100 m au-dessus de laquelle toutes les tranches visibles sont enneigées à plus de 50 %.
    """
    clear = values >= 0
    if clear.sum() < MIN_BAND_PX:
        return None, float("nan"), float("nan")
    e, snow = elevations[clear], values[clear] >= SNOW_NDSI
    bands = np.floor(e / BAND_M).astype(int)
    stats = {b: snow[bands == b].mean() for b in np.unique(bands) if (bands == b).sum() >= MIN_BAND_PX}
    line = None
    for b in sorted(stats, reverse=True):  # du haut vers le bas, tant que c'est enneigé
        if stats[b] < 0.5:
            break
        line = b * BAND_M
    return (float(line) if line is not None else None), float(e.min()), float(e.max())


@dataclass
class PointSnow:
    """État de la neige en un point du tracé."""

    seen: bool | None  # neige vue par satellite (True/False) ; None : nuage ou pas d'image
    seen_day: date | None
    depth_cm: float | None  # épaisseur modélisée
    fresh: bool  # neige tombée récemment (non tassée)


def factor(depth_cm: float | None, fresh: bool, snowshoes: bool) -> float:
    if depth_cm is None:
        depth_cm = 0.0
    for max_cm, need_fresh, foot, shoes in FACTORS:
        if need_fresh is not None and need_fresh != fresh:
            continue
        if max_cm is None or depth_cm <= max_cm:
            return shoes if snowshoes else foot
    return 1.0


def snowy(p: PointSnow, line_m: float | None, ele: float | None) -> bool:
    """Neige probable en ce point : vue par satellite ; sinon (nuage) au-dessus de la limite observée ; sinon
    selon le modèle (épaisseur ≥ 2 cm)."""
    if p.seen is not None:
        return p.seen
    if line_m is not None and ele is not None:
        return ele >= line_m
    return (p.depth_cm or 0) >= 2


def duration_with_snow(
    points: list[TrackPoint],
    cum_m: np.ndarray,
    states: list[tuple[int, PointSnow]],
    line_m: float | None,
    profile: WalkerProfile,
    snowshoes: bool,
) -> tuple[int, int, float, list[tuple[float, float, float]]]:
    """(durée normale, durée avec neige en min, km enneigés, tronçons enneigés (km début, km fin, facteur)).

    Chaque échantillon `states` (indice du point, état) vaut pour le tronçon jusqu'à l'échantillon suivant.
    """
    total = normal = 0.0
    snow_km = 0.0
    sections: list[tuple[float, float, float]] = []
    for k, (i, st) in enumerate(states):
        j = states[k + 1][0] if k + 1 < len(states) else len(points) - 1
        if j <= i:
            continue
        seg = points[i : j + 1]
        eles = np.array([p.ele if p.ele is not None else np.nan for p in seg], dtype=float)
        d = np.diff(eles)
        up, down = float(np.nansum(np.clip(d, 0, None))), float(np.nansum(np.clip(-d, 0, None)))
        km = (cum_m[j] - cum_m[i]) / 1000
        minutes = estimate_minutes(km, up, down, profile)
        f = factor(st.depth_cm, st.fresh, snowshoes) if snowy(st, line_m, points[i].ele) else 1.0
        normal += minutes
        total += minutes * f
        if f > 1:
            snow_km += km
            a, b = cum_m[i] / 1000, cum_m[j] / 1000
            if sections and abs(sections[-1][1] - a) < 1e-6 and sections[-1][2] == f:
                sections[-1] = (sections[-1][0], b, f)
            else:
                sections.append((a, b, f))
    return round(normal), round(total), snow_km, sections
