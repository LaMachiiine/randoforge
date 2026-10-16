"""Itinéraires officiels publiés via Geotrek (parcs nationaux) : tracé, distance et D+ des topo-guides.

Deux usages :
- **pour l'utilisateur** : retrouver et importer la rando officielle d'un parc (`search`, `trek`) ;
- **pour la calibration et les tests** : référence de D+ (`treks`). Le D+ publié est lui-même calculé par Geotrek
  sur un MNT : c'est une référence *officielle et cohérente*, pas une mesure terrain indépendante
  (voir docs/10 - Architecture/Calcul du dénivelé.md).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from ..http import DAY, CachedHttp

# Registre des catalogues Geotrek publics (parcs nationaux et régionaux, départements, intercommunalités),
# généré par scripts/build_geotrek_catalogs.py : nom, API, nombre de randos pédestres, emprise des départs.
CATALOGS: dict[str, dict] = {
    c["id"]: c for c in json.loads((Path(__file__).with_name("geotrek_catalogs.json")).read_text(encoding="utf-8"))
}
INSTANCES = {cid: f"{c['api']}trek/" for cid, c in CATALOGS.items()}
PARKS = {cid: c["nom"] for cid, c in CATALOGS.items()}  # nom affiché de chaque catalogue

WALKING_WORDS = ("pied", "pédestre", "pedestre", "marche", "rando", "promenade", "balade", "découverte")
NOT_WALKING_WORDS = ("vtt", "vélo", "velo", "cyclo", "cheval", "équestre", "equestre", "trail", "raquette", "ski",
                     "canoë", "canoe", "gravel", "nordique", "attelage")  # fmt: skip


def is_walking(name) -> bool:
    """Pratique de randonnée pédestre (« A pied », « Pédestre », « Randonnée »…), hors VTT, trail, raquette…"""
    n = _name(name).lower()
    return any(w in n for w in WALKING_WORDS) and not any(w in n for w in NOT_WALKING_WORDS)


def catalogs_near(lat: float, lon: float, margin_deg: float = 0.0) -> list[str]:
    """Catalogues dont l'emprise contient le point (à `margin_deg` près)."""
    return [
        cid
        for cid, c in CATALOGS.items()
        if c["bbox"][0] - margin_deg <= lat <= c["bbox"][2] + margin_deg
        and c["bbox"][1] - margin_deg <= lon <= c["bbox"][3] + margin_deg
    ]


FIELDS = "id,name,ascent,descent,length_2d,min_elevation,max_elevation,geometry"
SEARCH_FIELDS = "id,name,departure,arrival,ascent,length_2d,route,description_teaser,departure_geom"


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


class OfficialTrek(BaseModel):
    """Rando officielle trouvée par `search` (sans géométrie : à importer avec `trek`)."""

    catalogue: str
    trek_id: int
    nom: str
    depart: str | None
    arrivee: str | None
    type: str | None
    distance_km: float | None
    d_plus_m: int | None
    resume: str | None
    depart_lat: float | None = None
    depart_lon: float | None = None


def _name(value) -> str:
    return value if isinstance(value, str) else (value or {}).get("fr") or next(iter((value or {}).values()), "")


def _usable(t: dict) -> bool:
    return bool(t.get("ascent")) and bool(t.get("length_2d")) and (t.get("geometry") or {}).get("type") == "LineString"


def _to_trek(instance: str, t: dict) -> ReferenceTrek:
    return ReferenceTrek(
        source=instance, id=t["id"], name=_name(t.get("name")), ascent_m=int(t["ascent"]),
        descent_m=abs(int(t.get("descent") or 0)), length_km=round(t["length_2d"] / 1000, 3),
        min_elevation_m=t.get("min_elevation"), max_elevation_m=t.get("max_elevation"),
        coords=[(c[1], c[0], c[2] if len(c) > 2 else None) for c in t["geometry"]["coordinates"]],
    )  # fmt: skip


class GeotrekReference:
    def __init__(self, http: CachedHttp):
        self.http = http

    def _get(self, instance: str, url: str, params: dict) -> dict:
        return self.http.request_json("GET", url, params=params, ttl_s=30 * DAY, service=f"Geotrek {instance}")

    def walking_practices(self, instance: str) -> list[int]:
        """Identifiants des pratiques pédestres (voir `is_walking`)."""
        res = self._get(instance, INSTANCES[instance].replace("/trek/", "/trek_practice/"),
                        {"format": "json", "language": "fr"})  # fmt: skip
        ids = [p["id"] for p in res.get("results", []) if is_walking(p.get("name"))]
        if not ids:  # sans filtre, Geotrek renverrait aussi VTT, trail, etc.
            raise ValueError(f"Geotrek {instance} : aucune pratique pédestre reconnue dans le catalogue")
        return ids

    def route_types(self, instance: str) -> dict[int, str]:
        res = self._get(
            instance, INSTANCES[instance].replace("/trek/", "/trek_route/"), {"format": "json", "language": "fr"}
        )
        return {r["id"]: r["route"] for r in res.get("results", [])}

    def trek(self, instance: str, trek_id: int) -> ReferenceTrek:
        """Un itinéraire précis, avec sa géométrie officielle."""
        t = self._get(
            instance, f"{INSTANCES[instance]}{trek_id}/", {"format": "json", "language": "fr", "fields": FIELDS}
        )
        if not _usable(t):
            raise ValueError(f"Itinéraire Geotrek {instance}/{trek_id} sans D+, distance ou tracé exploitable")
        return _to_trek(instance, t)

    def search(
        self,
        instance: str,
        query: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 20,
    ) -> list[OfficialTrek]:
        """Randos pédestres officielles par nom (`query`) et/ou zone (`bbox` = sud, ouest, nord, est)."""
        params = {"format": "json", "language": "fr", "fields": SEARCH_FIELDS, "page_size": limit,
                  "practices": ",".join(map(str, self.walking_practices(instance)))}  # fmt: skip
        if query:
            params["q"] = query
        if bbox:
            s, w, n, e = bbox
            params["in_bbox"] = f"{w:.5f},{s:.5f},{e:.5f},{n:.5f}"
        types = self.route_types(instance)
        out = []
        for t in self._get(instance, INSTANCES[instance], params).get("results", []):
            geom = t.get("departure_geom")  # [lon, lat] ou objet GeoJSON selon la version de Geotrek
            dep = (geom.get("coordinates") if isinstance(geom, dict) else geom) or [None, None]
            teaser = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _name(t.get("description_teaser")))).strip()
            out.append(OfficialTrek(
                catalogue=instance, trek_id=t["id"], nom=_name(t.get("name")), depart=t.get("departure") or None,
                arrivee=t.get("arrival") or None, type=types.get(t.get("route")),
                distance_km=round(t["length_2d"] / 1000, 2) if t.get("length_2d") else None,
                d_plus_m=t.get("ascent"), resume=teaser[:240] or None, depart_lat=dep[1], depart_lon=dep[0],
            ))  # fmt: skip
        return out

    def treks(self, instance: str, limit: int = 20, page_size: int = 50) -> list[ReferenceTrek]:
        """Itinéraires pédestres simples (une seule ligne), répartis sur tout le catalogue (calibration, tests)."""
        url = INSTANCES[instance]
        params = {"format": "json", "language": "fr", "fields": FIELDS, "page_size": page_size, "ordering": "id",
                  "practices": ",".join(map(str, self.walking_practices(instance)))}  # fmt: skip
        first = self._get(instance, url, params)
        pages = max(1, -(-first.get("count", 0) // page_size))
        # Échantillon réparti sur tout le catalogue : quelques itinéraires par page, pages espacées.
        sampled = sorted({1 + round(i * (pages - 1) / max(1, min(pages, limit) - 1)) for i in range(min(pages, limit))})
        per_page = -(-limit // len(sampled))
        out: list[ReferenceTrek] = []
        for page in sampled:
            data = first if page == 1 else self._get(instance, url, {**params, "page": page})
            usable = [t for t in data.get("results", []) if _usable(t)][:per_page]
            out += [_to_trek(instance, t) for t in usable]
            if len(out) >= limit:
                return out[:limit]
        return out
