"""Génération de boucles candidates par « triangles » autour du départ.

Pour une direction donnée, on place deux points d'attraction à distance r du départ,
écartés de 60° : départ → P1 → P2 → départ forme un triangle équilatéral de périmètre 3r.
Les chemins réels serpentent ; on corrige r d'après la distance obtenue par le moteur.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geo import GEOD

INITIAL_WINDING = 1.3  # longueur réelle / périmètre à vol d'oiseau, à corriger après un premier essai
HALF_ANGLE = 30.0


def destination(lat: float, lon: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    lon2, lat2, _ = GEOD.fwd(lon, lat, bearing_deg, dist_m)
    return lat2, lon2


def triangle(start: tuple[float, float], bearing_deg: float, radius_m: float) -> list[tuple[float, float]]:
    p1 = destination(*start, bearing_deg - HALF_ANGLE, radius_m)
    p2 = destination(*start, bearing_deg + HALF_ANGLE, radius_m)
    return [start, p1, p2, start]


def initial_radius(target_m: float) -> float:
    return target_m / (3 * INITIAL_WINDING)


def corrected_radius(radius_m: float, target_m: float, actual_m: float) -> float:
    """Règle de trois, bornée pour éviter les corrections extrêmes sur un essai aberrant."""
    ratio = min(2.0, max(0.5, target_m / actual_m)) if actual_m > 0 else 1.0
    return radius_m * ratio


def bearings(n: int) -> list[float]:
    return [i * 360.0 / n for i in range(n)]


@dataclass
class CandidateScore:
    distance_err: float
    d_plus_err: float
    retrace_frac: float
    tarmac_frac: float

    @property
    def total(self) -> float:
        """Plus petit = meilleur. L'aller-retour et le goudron sont pénalisés plus que l'écart de distance."""
        return self.distance_err + 0.7 * self.d_plus_err + 1.5 * self.retrace_frac + 0.8 * self.tarmac_frac


def score(
    distance_m: float,
    target_m: float,
    d_plus_m: float | None,
    target_d_plus_m: float | None,
    retrace_m: float,
    tarmac_m: float,
) -> CandidateScore:
    d_plus_err = 0.0
    if target_d_plus_m and d_plus_m is not None:
        d_plus_err = abs(d_plus_m - target_d_plus_m) / target_d_plus_m
    return CandidateScore(
        distance_err=abs(distance_m - target_m) / target_m,
        d_plus_err=d_plus_err,
        retrace_frac=retrace_m / distance_m if distance_m else 0,
        tarmac_frac=tarmac_m / distance_m if distance_m else 0,
    )
