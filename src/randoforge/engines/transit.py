"""Horaires de transport en commun autour d'un point : Transitous (MOTIS), sans clé, Europe.

Transitous agrège les horaires officiels (GTFS) des réseaux européens. Conditions d'usage : projet open source
et non commercial, User-Agent identifiant, attribution visible vers https://transitous.org/sources/ (données
sources ODbL en France via transport.data.gouv.fr). Horaires théoriques (pas de temps réel observé).
"""

from __future__ import annotations

from datetime import datetime

from ..http import CachedHttp

URL = "https://api.transitous.org/api/v6/stoptimes"
ATTRIBUTION = "Horaires : Transitous (transitous.org/sources), données des réseaux (ODbL)"


class Transitous:
    name = "Transitous"

    def __init__(self, http: CachedHttp, url: str | None = None):
        self.http = http
        self.url = url or URL

    def stop_times(self, lat: float, lon: float, start_utc: datetime, radius_m: int = 800, n: int = 200) -> list[dict]:
        """Passages aux arrêts à moins de `radius_m` du point, à partir de `start_utc` (les `n` suivants)."""
        params = {
            "center": f"{lat:.5f},{lon:.5f}",
            "radius": radius_m,
            "time": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n": n,
            "language": "fr",
        }
        res = self.http.request_json("GET", self.url, params=params, ttl_s=6 * 3600, service="Transitous")
        return res.get("stopTimes", [])
