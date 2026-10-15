"""Estimation de la durée de marche (méthode DIN 33466, utilisée par les clubs alpins)."""

from __future__ import annotations

from .models import WalkerProfile


def estimate_minutes(distance_km: float, d_plus_m: float, d_minus_m: float, profile: WalkerProfile) -> int:
    """Durée de marche effective, pauses exclues.

    t_h = distance / vitesse à plat ; t_v = D+ / vitesse montée + D- / vitesse descente ;
    durée = max(t_h, t_v) + min(t_h, t_v) / 2.
    """
    t_h = distance_km / profile.flat_kmh
    t_v = d_plus_m / profile.up_m_per_h + d_minus_m / profile.down_m_per_h
    hours = max(t_h, t_v) + min(t_h, t_v) / 2
    return round(hours * 60)


def format_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}"
