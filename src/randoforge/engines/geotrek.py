"""Itinéraires officiels publiés via Geotrek (parcs nationaux) : tracé, distance et D+ des topo-guides.

Sert de référence pour calibrer et tester le calcul du dénivelé. Le D+ publié est lui-même
calculé par Geotrek sur un MNT : c'est une référence *officielle et cohérente*, pas une mesure
terrain indépendante (voir docs/10 - Architecture/Calcul du dénivelé.md).
"""

from __future__ import annotations

from pydantic import BaseModel

from ..http import DAY, CachedHttp

INSTANCES = {
    "ecrins": "https://geotrek-admin.ecrins-parcnational.fr/api/v2/trek/",
    "cevennes": "https://geotrek-admin.cevennes-parcnational.net/api/v2/trek/",
}
FIELDS = "id,name,ascent,descent,length_2d,min_elevation,max_elevation,geometry"


class ReferenceTrek(BaseModel):
    source: str
    id: int
    name: str
    ascent_m: int
    descent_m: int
    length_km: float
    min_elevation_m: float | None
    max_elevation_m: float | None
    coords: list[tuple[float, float, float | None]]  # (lat, lon, altitude Geotrek)


def _name(value) -> str:
    return value if isinstance(value, str) else (value or {}).get("fr") or next(iter((value or {}).values()), "")


class GeotrekReference:
    def __init__(self, http: CachedHttp):
        self.http = http

    def walking_practices(self, instance: str) -> list[int]:
        """Identifiants des pratiques pédestres (« A pied », « Rando à pied », « Sentiers de découverte »)."""
        url = INSTANCES[instance].replace("/trek/", "/trek_practice/")
        res = self.http.request_json("GET", url, params={"format": "json", "language": "fr"}, ttl_s=30 * DAY,
                                     service=f"Geotrek {instance}")  # fmt: skip
        return [
            p["id"]
            for p in res.get("results", [])
            if any(k in _name(p.get("name")).lower() for k in ("pied", "découverte"))
        ]

    def treks(self, instance: str, limit: int = 20, page_size: int = 50) -> list[ReferenceTrek]:
        """Itinéraires pédestres simples (une seule ligne), répartis sur tout le catalogue."""
        url = INSTANCES[instance]
        params = {"format": "json", "language": "fr", "fields": FIELDS, "page_size": page_size, "ordering": "id",
                  "practices": ",".join(map(str, self.walking_practices(instance)))}  # fmt: skip
        first = self.http.request_json("GET", url, params=params, ttl_s=30 * DAY, service=f"Geotrek {instance}")
        pages = max(1, -(-first.get("count", 0) // page_size))
        # Échantillon réparti sur tout le catalogue : quelques itinéraires par page, pages espacées.
        sampled = sorted({1 + round(i * (pages - 1) / max(1, min(pages, limit) - 1)) for i in range(min(pages, limit))})
        per_page = -(-limit // len(sampled))
        out: list[ReferenceTrek] = []
        for page in sampled:
            taken = 0
            data = (
                first
                if page == 1
                else self.http.request_json(
                    "GET", url, params={**params, "page": page}, ttl_s=30 * DAY, service=f"Geotrek {instance}"
                )
            )
            for t in data.get("results", []):
                g = t.get("geometry") or {}
                if g.get("type") != "LineString" or not t.get("ascent") or not t.get("length_2d"):
                    continue
                out.append(ReferenceTrek(
                    source=instance, id=t["id"], name=_name(t.get("name")), ascent_m=int(t["ascent"]),
                    descent_m=abs(int(t.get("descent") or 0)), length_km=round(t["length_2d"] / 1000, 3),
                    min_elevation_m=t.get("min_elevation"), max_elevation_m=t.get("max_elevation"),
                    coords=[(c[1], c[0], c[2] if len(c) > 2 else None) for c in g["coordinates"]],
                ))  # fmt: skip
                taken += 1
                if len(out) >= limit:
                    return out
                if taken >= per_page:
                    break
        return out
