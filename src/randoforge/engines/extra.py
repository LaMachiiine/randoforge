"""Clients externes complémentaires : refuges.info, Open-Meteo, Wikidata."""

from __future__ import annotations

from datetime import date, timedelta

from ..http import DAY, CachedHttp


class RefugesInfo:
    """Points de refuges.info (cabanes, refuges, gîtes, points d'eau, passages délicats…).

    Données sous licence CC BY-SA, contributeurs refuges.info.
    """

    URL = "https://www.refuges.info/api/bbox"

    def __init__(self, http: CachedHttp):
        self.http = http

    def points(self, south: float, west: float, north: float, east: float) -> list[dict]:
        params = {
            "bbox": f"{west:.5f},{south:.5f},{east:.5f},{north:.5f}",
            "type_points": "all",
            "format": "geojson",
            "detail": "complet",
        }
        res = self.http.request_json("GET", self.URL, params=params, ttl_s=7 * DAY, service="refuges.info")
        out = []
        for f in res.get("features", []):
            p = f.get("properties", {})
            coord = p.get("coord") or {}
            geo = (f.get("geometry") or {}).get("coordinates") or [None, None]
            lat, lon = coord.get("lat", geo[1]), coord.get("long", geo[0])
            if lat is None or lon is None:
                continue  # point sans coordonnées : ignoré
            places = (p.get("places") or {}).get("valeur")
            out.append(
                {
                    "id": p.get("id"),
                    "nom": p.get("nom") or "",
                    "type": (p.get("type") or {}).get("valeur", ""),
                    "lat": float(lat),
                    "lon": float(lon),
                    "alt": coord.get("alt"),
                    "places": places if isinstance(places, int) else None,
                    "lien": p.get("lien"),
                }
            )
        return out


class OpenMeteo:
    """Prévisions horaires (16 jours max), y compris en altitude et hauteur de neige. Sans clé."""

    URL = "https://api.open-meteo.com/v1/forecast"
    HOURLY = "temperature_2m,precipitation,weather_code,wind_gusts_10m,snow_depth,cape"

    def __init__(self, http: CachedHttp):
        self.http = http

    def hourly(self, lat: float, lon: float, elevation: float | None, day: date) -> dict:
        params = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "hourly": self.HOURLY,
            "timezone": "auto",
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
        }
        if elevation is not None:  # sinon Open-Meteo prend l'altitude de son propre MNT
            params["elevation"] = round(elevation)
        # Prévision : cache court (3 h)
        return self.http.request_json("GET", self.URL, params=params, ttl_s=3 * 3600, service="Open-Meteo")


def _snow_series(entry: dict, day: date) -> dict:
    h = entry.get("hourly", {})
    times = h.get("time", [])
    depth = [v for t, v in zip(times, h.get("snow_depth", []), strict=False) if t.startswith(day.isoformat())]
    fall = [v for v in h.get("snowfall", []) if v is not None]
    return {
        "snow_depth_m": max((v for v in depth if v is not None), default=None),
        "snowfall_72h_cm": round(sum(fall[-72:]), 1) if fall else None,
        "model_elevation_m": entry.get("elevation"),
    }


class OpenMeteoSnow:
    """Épaisseur de neige et neige fraîche **modélisées** (Open-Meteo, meilleur modèle disponible) en plusieurs
    points, le jour donné. L'épaisseur n'est pas recalculée pour l'altitude exacte : Open-Meteo choisit la maille
    d'altitude la plus proche ; les modèles divergent fortement en relief (estimation, pas mesure)."""

    URL = "https://api.open-meteo.com/v1/forecast"
    ARCHIVE_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"  # au-delà de ~3 mois

    def __init__(self, http: CachedHttp):
        self.http = http

    def snow(self, points: list[tuple[float, float, float | None]], day: date) -> list[dict]:
        if not points:
            return []
        params = {
            "latitude": ",".join(f"{la:.4f}" for la, _, _ in points),
            "longitude": ",".join(f"{lo:.4f}" for _, lo, _ in points),
            # Altitude réelle : Open-Meteo choisit une maille d'altitude proche (l'épaisseur n'est pas recalculée).
            "elevation": ",".join("nan" if e is None else f"{e:.0f}" for _, _, e in points),
            "hourly": "snow_depth,snowfall",
            "timezone": "auto",
            "start_date": (day - timedelta(days=3)).isoformat(),
            "end_date": day.isoformat(),
        }
        old = day < date.today() - timedelta(days=80)
        res = self.http.request_json("GET", self.ARCHIVE_URL if old else self.URL, params=params,
                                     ttl_s=None if old else 3 * 3600, service="Open-Meteo (neige)")  # fmt: skip
        entries = res if isinstance(res, list) else [res]
        return [_snow_series(e, day) for e in entries]


class Wikidata:
    URL = "https://www.wikidata.org/w/api.php"

    def __init__(self, http: CachedHttp):
        self.http = http

    def describe(self, ids: list[str], lang: str = "fr") -> dict[str, dict]:
        """{Qid: {"description": ..., "wikipedia": url}} pour les entités connues."""
        out: dict[str, dict] = {}
        for i in range(0, len(ids), 50):
            chunk = ids[i : i + 50]
            params = {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "props": "descriptions|sitelinks",
                "languages": lang,
                "sitefilter": f"{lang}wiki",
                "format": "json",
            }
            res = self.http.request_json("GET", self.URL, params=params, ttl_s=90 * DAY, service="Wikidata")
            for qid, ent in res.get("entities", {}).items():
                desc = ent.get("descriptions", {}).get(lang, {}).get("value")
                link = ent.get("sitelinks", {}).get(f"{lang}wiki", {}).get("title")
                out[qid] = {
                    "description": desc,
                    "wikipedia": f"https://{lang}.wikipedia.org/wiki/{link.replace(' ', '_')}" if link else None,
                }
        return out
