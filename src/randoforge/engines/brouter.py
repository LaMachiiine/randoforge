"""Moteur de routage BRouter (https://brouter.de), profils randonnée."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.models import TrackPoint, WaySegment
from ..http import DAY, CachedHttp

PROFILES = {
    "hiking-mountain": "Randonnée, y compris sentiers de montagne (sac_scale pris en compte)",
    "hiking-beta": "Randonnée, variante expérimentale",
    "shortest": "Plus court chemin praticable, sans préférence",
}


@dataclass
class RoutingResult:
    points: list[TrackPoint]
    segments: list[WaySegment]
    engine_stats: dict[str, float] = field(default_factory=dict)


def parse_waytags(raw: str) -> dict[str, str]:
    tags = {}
    for kv in raw.split():
        k, _, v = kv.partition("=")
        tags[k] = v
    return tags


def parse_geojson(data: dict) -> RoutingResult:
    """Convertit la réponse GeoJSON de BRouter.

    `messages` liste les portions de tracé de tags homogènes ; leur colonne `Distance`
    est la longueur de chaque portion (la somme vaut `track-length`).
    """
    feature = data["features"][0]
    props = feature["properties"]
    # On ignore l'altitude BRouter (SRTM) : elle est recalculée par notre chaîne altimétrique.
    points = [TrackPoint(lat=c[1], lon=c[0]) for c in feature["geometry"]["coordinates"]]

    segments: list[WaySegment] = []
    messages = props.get("messages") or []
    if messages:
        header = messages[0]
        i_dist, i_tags = header.index("Distance"), header.index("WayTags")
        pos = 0.0
        for row in messages[1:]:
            length = float(row[i_dist])
            segments.append(WaySegment(start_m=pos, end_m=pos + length, tags=parse_waytags(row[i_tags])))
            pos += length

    stats = {
        "distance_m": float(props.get("track-length", 0)),
        "d_plus_m": float(props.get("filtered ascend", 0)),
    }
    return RoutingResult(points, segments, stats)


class BRouterEngine:
    name = "BRouter"

    def __init__(self, http: CachedHttp, base_url: str = "https://brouter.de/brouter"):
        self.http = http
        self.base_url = base_url

    def route(self, waypoints: list[tuple[float, float]], profile: str) -> RoutingResult:
        if profile not in PROFILES:
            raise ValueError(f"Profil inconnu : {profile}. Profils disponibles : {', '.join(PROFILES)}")
        params = {
            "lonlats": "|".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints),
            "profile": profile,
            "alternativeidx": 0,
            "format": "geojson",
        }
        data = self.http.request_json("GET", self.base_url, params=params, ttl_s=7 * DAY, service="BRouter")
        return parse_geojson(data)
