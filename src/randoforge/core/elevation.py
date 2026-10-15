"""Lissage altimétrique et calcul du dénivelé cumulé par hystérésis."""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def median_smooth(eles: np.ndarray, window_pts: int) -> np.ndarray:
    """Filtre médian glissant centré ; les bords sont prolongés par réplication."""
    if window_pts <= 1 or len(eles) < 3:
        return eles.copy()
    if window_pts % 2 == 0:
        window_pts += 1
    half = window_pts // 2
    padded = np.pad(eles, half, mode="edge")
    return np.median(sliding_window_view(padded, window_pts), axis=1)


def elevation_gain(eles: np.ndarray, threshold_m: float) -> tuple[float, float]:
    """D+ et D- cumulés, en ignorant les oscillations inférieures à `threshold_m`.

    On suit les extremums : une montée n'est validée qu'au moment où l'on redescend
    d'au moins `threshold_m` depuis le point le plus haut atteint (et inversement).
    Contrairement à un simple seuil sur le dernier point validé, on ne perd pas
    jusqu'à `threshold_m` à chaque sommet ou col.
    """
    if len(eles) < 2:
        return 0.0, 0.0
    up = down = 0.0
    last = cand = float(eles[0])  # dernier extremum validé / extremum candidat
    direction = 0  # 1 = montée, -1 = descente, 0 = indéterminé
    for a in map(float, eles[1:]):
        if direction == 0:
            if a - last >= threshold_m:
                direction, cand = 1, a
            elif last - a >= threshold_m:
                direction, cand = -1, a
        elif direction == 1:
            if a > cand:
                cand = a
            elif cand - a >= threshold_m:
                up += cand - last
                last, cand, direction = cand, a, -1
        else:
            if a < cand:
                cand = a
            elif a - cand >= threshold_m:
                down += last - cand
                last, cand, direction = cand, a, 1
    if direction == 1:
        up += cand - last
    elif direction == -1:
        down += last - cand
    return up, down
