"""Synthèse des prévisions horaires Open-Meteo sur la plage horaire de marche."""

from __future__ import annotations

from .models import WeatherWindow

STORM_CODES = set(range(95, 100))  # codes WMO orage
CAPE_STORM = 1000.0  # J/kg : atmosphère instable, risque d'orage
GUSTS_KMH = 60.0
RAIN_MM = 5.0
SNOW_M = 0.1


def summarize(data: dict, place: str, altitude_m: float, hours: range) -> WeatherWindow:
    h = data.get("hourly", {})
    idx = [i for i, t in enumerate(h.get("time", [])) if int(t[11:13]) in hours]

    def pick(key: str) -> list[float]:
        values = h.get(key) or []
        return [values[i] for i in idx if i < len(values) and values[i] is not None]

    temps, rain, gusts, snow, cape, codes = (
        pick(k) for k in ("temperature_2m", "precipitation", "wind_gusts_10m", "snow_depth", "cape", "weather_code")
    )
    return WeatherWindow(
        lieu=place,
        altitude_m=round(altitude_m),
        temp_min_c=min(temps, default=None),
        temp_max_c=max(temps, default=None),
        pluie_mm=round(sum(rain), 1) if rain else None,
        rafales_max_kmh=max(gusts, default=None),
        neige_m=max(snow, default=None),
        orage=any(int(c) in STORM_CODES for c in codes) or any(c >= CAPE_STORM for c in cape),
    )


def alerts(windows: list[WeatherWindow]) -> list[str]:
    out = []
    for w in windows:
        where = f"{w.lieu} ({w.altitude_m:.0f} m)"
        if w.orage:
            out.append(f"Risque d'orage à {where} : partir tôt, éviter crêtes et sommets l'après-midi")
        if w.pluie_mm is not None and w.pluie_mm >= RAIN_MM:
            out.append(f"Pluie {w.pluie_mm} mm à {where} : sentiers glissants, gués plus hauts")
        if w.rafales_max_kmh is not None and w.rafales_max_kmh >= GUSTS_KMH:
            out.append(f"Rafales jusqu'à {w.rafales_max_kmh:.0f} km/h à {where}")
        if w.neige_m is not None and w.neige_m >= SNOW_M:
            out.append(f"Neige au sol ~{w.neige_m * 100:.0f} cm à {where}")
        if w.temp_min_c is not None and w.temp_min_c <= 0:
            out.append(f"Gel possible à {where} ({w.temp_min_c:.0f} °C)")
    return list(dict.fromkeys(out))
