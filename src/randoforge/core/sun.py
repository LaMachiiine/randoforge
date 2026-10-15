"""Lever et coucher du soleil, hors ligne (équation du lever de soleil, précision ~1–2 min)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

J2000 = 2451545.0


def _jd_to_datetime(jd: float) -> datetime:
    return datetime(2000, 1, 1, 12, tzinfo=UTC) + timedelta(days=jd - J2000)


def sun_times(lat: float, lon: float, day: date, elevation_m: float = 0.0) -> tuple[datetime, datetime] | None:
    """(lever, coucher) en UTC ; None en cas de jour ou de nuit polaire.

    L'altitude abaisse l'horizon apparent : le soleil se couche plus tard en montagne dégagée.
    """
    # Date julienne à 0 h UTC du jour demandé (à midi, on calculerait le lendemain).
    jd_midnight = day.toordinal() + 1721424.5
    n = math.ceil(jd_midnight - J2000 + 0.0008)
    j_star = n - lon / 360.0
    m = math.radians((357.5291 + 0.98560028 * j_star) % 360)
    c = 1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    lam = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    j_transit = J2000 + j_star + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * lam)
    sin_d = math.sin(lam) * math.sin(math.radians(23.4397))
    cos_d = math.cos(math.asin(sin_d))
    h0 = -0.833 - 2.076 * math.sqrt(max(elevation_m, 0)) / 60
    phi = math.radians(lat)
    cos_w = (math.sin(math.radians(h0)) - math.sin(phi) * sin_d) / (math.cos(phi) * cos_d)
    if not -1 <= cos_w <= 1:
        return None
    w = math.degrees(math.acos(cos_w))
    return _jd_to_datetime(j_transit - w / 360), _jd_to_datetime(j_transit + w / 360)


_finder = None


def timezone_at(lat: float, lon: float) -> ZoneInfo:
    """Fuseau horaire du lieu (hors ligne) ; UTC si inconnu (en mer)."""
    global _finder
    if _finder is None:
        from timezonefinder import TimezoneFinder

        _finder = TimezoneFinder()
    name = _finder.timezone_at(lat=lat, lng=lon)
    return ZoneInfo(name or "UTC")
