"""Statistiques d'un tracé : distance, dénivelé, altitudes, durée."""

from __future__ import annotations

import numpy as np

from .elevation import elevation_gain, median_smooth
from .geo import cumulative_distance, distance_m, resample
from .models import ElevationParams, RouteStats, TrackPoint, WalkerProfile
from .timing import estimate_minutes, format_duration

LOOP_TOLERANCE_M = 50.0


def compute_stats(
    points: list[TrackPoint],
    params: ElevationParams | None = None,
    profile: WalkerProfile | None = None,
    elevation_source: str = "inconnue",
) -> tuple[RouteStats, list[str]]:
    """Calcule les statistiques et renvoie aussi les avertissements rencontrés.

    Si une partie des altitudes manque, les stats d'altitude valent None plutôt
    qu'une valeur silencieusement fausse.
    """
    params = params or ElevationParams()
    profile = profile or WalkerProfile()
    warnings: list[str] = []

    if len(points) < 2:
        raise ValueError("Un tracé doit contenir au moins 2 points.")

    lats = np.array([p.lat for p in points])
    lons = np.array([p.lon for p in points])
    distance_km = float(cumulative_distance(lats, lons)[-1]) / 1000
    is_loop = distance_m((points[0].lat, points[0].lon), (points[-1].lat, points[-1].lon)) <= LOOP_TOLERANCE_M

    d_plus = d_minus = alt_min = alt_max = None
    duration_min = None
    missing = sum(p.ele is None for p in points)
    if missing:
        warnings.append(
            f"{missing}/{len(points)} points sans altitude : dénivelé non calculé. "
            "Il faudra récupérer l'altitude depuis un MNT."
        )
    else:
        eles = np.array([p.ele for p in points], dtype=float)
        _, _, _, e = resample(lats, lons, eles, params.step_m)
        window_pts = int(round(params.smooth_window_m / params.step_m))
        e = median_smooth(e, window_pts)
        up, down = elevation_gain(e, params.threshold_m)
        d_plus, d_minus = round(up), round(down)
        alt_min, alt_max = round(float(e.min())), round(float(e.max()))
        if is_loop and max(up, down) > 0 and abs(up - down) / max(up, down) > 0.01:
            warnings.append(f"Boucle avec D+ ({d_plus} m) ≠ D- ({d_minus} m) de plus de 1 % : altitudes incohérentes ?")

    if d_plus is not None:
        duration_min = estimate_minutes(distance_km, d_plus, d_minus, profile)

    stats = RouteStats(
        distance_km=round(distance_km, 2),
        d_plus_m=d_plus,
        d_minus_m=d_minus,
        alt_min_m=alt_min,
        alt_max_m=alt_max,
        duration_min=duration_min,
        duration_label=format_duration(duration_min) if duration_min is not None else None,
        is_loop=is_loop,
        elevation_source=elevation_source,
        params=params,
        profile=profile,
    )
    return stats, warnings
