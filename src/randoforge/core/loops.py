"""Génération de boucles candidates par « triangles » autour du départ.

Pour une direction donnée, on place deux points d'attraction à distance r du départ,
écartés de 60° : départ → P1 → P2 → départ forme un triangle équilatéral de périmètre 3r.
Les chemins réels serpentent ; on corrige r d'après la distance obtenue par le moteur.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .geo import GEOD, cumulative_distance
from .models import TrackPoint, WaySegment

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
    marked_frac: float = 0.0
    done_frac: float = 0.0

    @property
    def total(self) -> float:
        """Plus petit = meilleur. L'aller-retour et le goudron sont pénalisés plus que l'écart de distance ;
        les sentiers balisés sont favorisés, le déjà-fait pénalisé (si demandé)."""
        return (
            self.distance_err
            + 0.7 * self.d_plus_err
            + 1.5 * self.retrace_frac
            + 0.8 * self.tarmac_frac
            - 0.2 * self.marked_frac
            + 0.6 * self.done_frac
        )


def score(
    distance_m: float,
    target_m: float,
    d_plus_m: float | None,
    target_d_plus_m: float | None,
    retrace_m: float,
    tarmac_m: float,
    marked_frac: float = 0.0,
    done_frac: float = 0.0,
) -> CandidateScore:
    d_plus_err = 0.0
    if target_d_plus_m and d_plus_m is not None:
        d_plus_err = abs(d_plus_m - target_d_plus_m) / target_d_plus_m
    return CandidateScore(
        distance_err=abs(distance_m - target_m) / target_m,
        d_plus_err=d_plus_err,
        retrace_frac=retrace_m / distance_m if distance_m else 0,
        tarmac_frac=tarmac_m / distance_m if distance_m else 0,
        marked_frac=marked_frac,
        done_frac=done_frac,
    )


# --- Épingles : aller-retour parasite vers un point d'attraction ----------------------------------

SPUR_SAME_M = 2.0  # deux points du tracé à moins de 2 m : le même nœud de chemin, à l'aller et au retour
SPUR_MIN_M = 10.0  # en dessous, ce n'est qu'un raccord
SPUR_MAX_SHARE = 0.3  # une « épingle » de plus de 30 % du parcours est la rando elle-même (aller-retour)
SPUR_PROTECT_M = 25.0  # épingle menant à un point imposé (sommet, lieu choisi) : voulue, conservée


def _close(a, b, tol_m: float) -> bool:
    dlat = (a.lat - b.lat) * 111_195.0
    dlon = (a.lon - b.lon) * 111_195.0 * math.cos(math.radians(a.lat))
    return dlat * dlat + dlon * dlon <= tol_m * tol_m


def spurs(points: list[TrackPoint], protect: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """Épingles du tracé : (a, b) tels que le tracé va de a à une pointe puis revient sur ses pas jusqu'à b,
    au même endroit que a. Le moteur de routage en crée quand un point d'attraction tombe à côté d'un chemin :
    il va au plus près, fait demi-tour et revient. Les épingles vers un point de `protect` sont conservées."""
    n = len(points)
    if n < 3:
        return []
    cum = cumulative_distance(np.array([p.lat for p in points]), np.array([p.lon for p in points]))
    out: list[tuple[int, int]] = []
    k = 1
    while k < n - 1:
        # Pointe : demi-tour sur un point (A, S, A) ou sur deux points confondus (A, S, S, A).
        if _close(points[k - 1], points[k + 1], SPUR_SAME_M):
            a, b = k - 1, k + 1
        elif (
            k + 2 < n
            and _close(points[k], points[k + 1], SPUR_SAME_M)
            and _close(points[k - 1], points[k + 2], SPUR_SAME_M)
        ):
            a, b = k - 1, k + 2
        else:
            k += 1
            continue
        while a > 0 and b < n - 1 and _close(points[a - 1], points[b + 1], SPUR_SAME_M):
            a, b = a - 1, b + 1
        length = cum[b] - cum[a]
        tip = points[k]
        protected = any(_close(tip, TrackPoint(lat=la, lon=lo), SPUR_PROTECT_M) for la, lo in protect)
        if SPUR_MIN_M <= length <= SPUR_MAX_SHARE * cum[-1] and not protected:
            out.append((a, b))
        k = b + 1
    return out


def remove_spurs(
    points: list[TrackPoint], segments: list[WaySegment], protect: list[tuple[float, float]]
) -> tuple[list[TrackPoint], list[WaySegment], float]:
    """Retire les épingles (voir `spurs`) ; recale les tronçons de chemin. Renvoie (points, tronçons, m retirés)."""
    found = spurs(points, protect)
    if not found:
        return points, segments, 0.0
    cum = cumulative_distance(np.array([p.lat for p in points]), np.array([p.lon for p in points]))
    scale = (segments[-1].end_m / cum[-1]) if segments and cum[-1] else 1.0  # tronçons : distances du moteur
    keep = np.ones(len(points), dtype=bool)
    cuts: list[tuple[float, float]] = []  # (début, longueur) en distance du moteur
    for a, b in found:
        keep[a + 1 : b + 1] = False
        cuts.append((cum[a] * scale, (cum[b] - cum[a]) * scale))
    new_segments: list[WaySegment] = []
    for seg in segments:
        pieces = [(seg.start_m, seg.end_m)]
        for start, length in cuts:  # on retire chaque intervalle coupé
            pieces = [p for s, e in pieces for p in ((s, min(e, start)), (max(s, start + length), e)) if p[1] > p[0]]
        for s, e in pieces:
            shift = sum(length for start, length in cuts if start + length <= s)
            new_segments.append(WaySegment(start_m=s - shift, end_m=e - shift, tags=seg.tags))
    removed = float(sum(cum[b] - cum[a] for a, b in found))
    return [p for p, k in zip(points, keep, strict=True) if k], new_segments, removed


SPUR_REPORT_M = 300.0  # aller-retour vers un point imposé : signalé au-delà de 300 m


def spur_notes(points: list[TrackPoint], waypoints: list[tuple[float, float]]) -> list[str]:
    """Allers-retours imposés par un point de passage au bout d'une impasse (sommet, belvédère…) : le moteur
    doit y aller et revenir par le même chemin. Ils ne sont pas retirés (le point a été demandé) mais signalés,
    avec le point en cause, pour proposer de le retirer ou de le remplacer."""
    found = spurs(points, [])
    if not found:
        return []
    lats, lons = np.array([p.lat for p in points]), np.array([p.lon for p in points])
    cum = cumulative_distance(lats, lons)
    notes = []
    for a, b in found:
        length = cum[b] - cum[a]
        if length < SPUR_REPORT_M:
            continue
        tip = (a + b) // 2  # pointe : milieu de l'aller-retour (même nombre de points à l'aller et au retour)
        near = [
            (i, w) for i, w in enumerate(waypoints, 1)
            if _close(points[tip], TrackPoint(lat=w[0], lon=w[1]), 150.0)
        ]  # fmt: skip
        target = f"vers le point de passage n°{near[0][0]}" if near else "vers une impasse"
        notes.append(
            f"Aller-retour de {length / 1000:.1f} km sur le même chemin au km {cum[a] / 1000:.1f} ({target}) : "
            "pour l'éviter, retirer ce point ou en choisir un sur un autre chemin."
        )
    return notes
