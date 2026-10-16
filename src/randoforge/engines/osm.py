"""Accès aux données OpenStreetMap : géocodage (Nominatim) et requêtes Overpass."""

from __future__ import annotations

from pydantic import BaseModel

from ..http import DAY, CachedHttp

# Ordre = priorité : du plus rapide mesuré au plus lent (les serveurs sont mis en concurrence, voir query()).
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
HEDGE_AFTER_S = 3.0
OVERPASS_ATTEMPTS = 6
OVERPASS_BUDGET_S = 180.0  # au-delà, l'outil répond « indisponible » plutôt que de faire attendre ~10 min


def overpass_problem(value) -> str | None:
    """Overpass renvoie parfois 200 avec une erreur d'exécution : ce n'est pas « aucun résultat »."""
    remark = str(value.get("remark") or "") if isinstance(value, dict) else ""
    return remark[:200] if "error" in remark.lower() else None


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

    def geocode(
        self, query: str, limit: int = 5, country: str | None = None, near: tuple[float, float] | None = None
    ) -> list[Place]:
        params = {"q": query, "format": "jsonv2", "limit": limit, "accept-language": "fr"}
        if country:
            params["countrycodes"] = country
        if near:
            # Préférence (non exclusive) pour les résultats à ~20 km du point donné.
            lat, lon = near
            params["viewbox"] = f"{lon - 0.25:.4f},{lat + 0.18:.4f},{lon + 0.25:.4f},{lat - 0.18:.4f}"
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
            "POST",
            self.urls,
            data={"data": ql},
            ttl_s=30 * DAY,
            service="Overpass (OpenStreetMap)",
            hedge_after_s=HEDGE_AFTER_S,
            accept=overpass_problem,
            # Les miroirs publics alternent erreurs 500/504 et succès d'une minute à l'autre (mesuré) :
            # davantage de tours d'essais rend la panne simultanée de tous les miroirs très improbable.
            attempts=OVERPASS_ATTEMPTS,
            budget_s=OVERPASS_BUDGET_S,
        )
        return res.get("elements", [])
