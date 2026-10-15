"""Accès aux données OpenStreetMap : géocodage (Nominatim) et requêtes Overpass."""

from __future__ import annotations

from pydantic import BaseModel

from ..http import DAY, CachedHttp

OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


class Place(BaseModel):
    name: str
    display_name: str
    lat: float
    lon: float
    type: str


class Nominatim:
    URL = "https://nominatim.openstreetmap.org/search"

    def __init__(self, http: CachedHttp, url: str | None = None):
        self.http = http
        self.url = url or self.URL

    def geocode(self, query: str, limit: int = 5, country: str | None = None) -> list[Place]:
        params = {"q": query, "format": "jsonv2", "limit": limit, "accept-language": "fr"}
        if country:
            params["countrycodes"] = country
        res = self.http.request_json("GET", self.url, params=params, ttl_s=90 * DAY, service="Nominatim")
        return [
            Place(
                name=r.get("name") or r["display_name"].split(",")[0],
                display_name=r["display_name"],
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                type=r.get("addresstype") or r.get("type", ""),
            )
            for r in res
        ]


class Overpass:
    def __init__(self, http: CachedHttp, urls: list[str] | None = None):
        self.http = http
        self.urls = urls or OVERPASS_URLS

    def query(self, ql: str) -> list[dict]:
        res = self.http.request_json(
            "POST", self.urls, data={"data": ql}, ttl_s=30 * DAY, service="Overpass (OpenStreetMap)"
        )
        return res.get("elements", [])
