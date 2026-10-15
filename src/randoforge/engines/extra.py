"""Clients externes complémentaires : refuges.info, Open-Meteo, Wikidata."""

from __future__ import annotations

from datetime import date

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
            coord = p.get("coord", {})
            places = (p.get("places") or {}).get("valeur")
            out.append(
                {
                    "id": p.get("id"),
                    "nom": p.get("nom") or "",
                    "type": (p.get("type") or {}).get("valeur", ""),
                    "lat": float(coord.get("lat", f["geometry"]["coordinates"][1])),
                    "lon": float(coord.get("long", f["geometry"]["coordinates"][0])),
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

    def hourly(self, lat: float, lon: float, elevation: float, day: date) -> dict:
        params = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "elevation": round(elevation),
            "hourly": self.HOURLY,
            "timezone": "auto",
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
        }
        # Prévision : cache court (3 h)
        return self.http.request_json("GET", self.URL, params=params, ttl_s=3 * 3600, service="Open-Meteo")


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
