"""Points notables (cascades, rivières, lacs, points de vue…) à partir d'éléments OSM.

Conception : docs/10 - Architecture/Points notables le long du tracé.md
Ce module ne fait aucun appel réseau : il reçoit les éléments Overpass (`out geom`).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from .geo import LocalProjection, cumulative_distance, lon_bounds
from .models import Poi, TrackPoint

ON_ROUTE_M = 50.0
FORD_MATCH_M = 25.0


@dataclass(frozen=True)
class Selector:
    ql: str  # filtre Overpass, sans la bbox
    match: Callable[[dict], str | None]  # renvoie le type (valeur du tag) si l'élément correspond


def _eq(key: str, value: str) -> Callable[[dict], str | None]:
    return lambda t: value if t.get(key) == value else None


def _in(key: str, values: set[str]) -> Callable[[dict], str | None]:
    return lambda t: t[key] if t.get(key) in values else None


NOT_LAKE = {"river", "stream", "canal", "ditch", "drain", "wastewater", "basin", "moat"}
NATURAL_CURIO = {"cave_entrance", "arch", "rock", "stone"}
HISTORIC = {
    "castle",
    "ruins",
    "wayside_cross",
    "wayside_shrine",
    "memorial",
    "archaeological_site",
    "monument",
}
HUTS = {"alpine_hut", "wilderness_hut"}

CATEGORIES: dict[str, tuple[float, list[Selector]]] = {
    "cascade": (1.0, [Selector('nwr["waterway"="waterfall"]', _eq("waterway", "waterfall"))]),
    "point_de_vue": (
        0.9,
        [
            Selector('nwr["tourism"="viewpoint"]', _eq("tourism", "viewpoint")),
            Selector(
                'nwr["tower:type"="observation"]',
                lambda t: "observation_tower" if t.get("tower:type") == "observation" else None,
            ),
        ],
    ),
    "lac": (
        0.8,
        [
            Selector(
                'nwr["natural"="water"]["water"!~"^(' + "|".join(sorted(NOT_LAKE)) + ')$"]',
                lambda t: (
                    (t.get("water") or "water")
                    if t.get("natural") == "water" and t.get("water") not in NOT_LAKE
                    else None
                ),
            )
        ],
    ),
    "sommet": (
        0.8,
        [
            Selector('node["natural"="peak"]', _eq("natural", "peak")),
            Selector('node["natural"="saddle"]', _eq("natural", "saddle")),
            Selector('node["mountain_pass"="yes"]', lambda t: "pass" if t.get("mountain_pass") == "yes" else None),
        ],
    ),
    "curiosite": (
        0.6,
        [
            Selector('nwr["natural"~"^(' + "|".join(sorted(NATURAL_CURIO)) + ')$"]', _in("natural", NATURAL_CURIO)),
            Selector(
                'node["natural"="tree"]["denotation"="natural_monument"]',
                lambda t: (
                    "remarkable_tree"
                    if t.get("natural") == "tree" and t.get("denotation") == "natural_monument"
                    else None
                ),
            ),
        ],
    ),
    "riviere": (0.4, [Selector('way["waterway"~"^(river|stream)$"]', _in("waterway", {"river", "stream"}))]),
    "patrimoine": (
        0.4,
        [
            Selector('nwr["historic"~"^(' + "|".join(sorted(HISTORIC)) + ')$"]', _in("historic", HISTORIC)),
            Selector('nwr["building"="chapel"]', _eq("building", "chapel")),
        ],
    ),
    "eau": (
        0.4,
        [
            Selector('node["natural"="spring"]', _eq("natural", "spring")),
            Selector('node["amenity"="drinking_water"]', _eq("amenity", "drinking_water")),
        ],
    ),
    "pause": (
        0.3,
        [
            Selector('nwr["tourism"="picnic_site"]', _eq("tourism", "picnic_site")),
            Selector(
                'nwr["amenity"="shelter"]["shelter_type"!="public_transport"]',
                lambda t: (
                    "shelter" if t.get("amenity") == "shelter" and t.get("shelter_type") != "public_transport" else None
                ),
            ),
            Selector('nwr["tourism"~"^(alpine_hut|wilderness_hut)$"]', _in("tourism", HUTS)),
        ],
    ),
    # Pas inclus par défaut : utile pour un départ/une arrivée en transports en commun.
    "transport": (
        0.2,
        [
            Selector('node["highway"="bus_stop"]', _eq("highway", "bus_stop")),
            Selector('nwr["railway"~"^(station|halt)$"]', _in("railway", {"station", "halt"})),
        ],
    ),
}
FORD = Selector('nwr["ford"="yes"]', _eq("ford", "yes"))


def build_query(bbox: tuple[float, float, float, float], categories: list[str]) -> str:
    """Requête Overpass pour une bbox (sud, ouest, nord, est)."""
    s, w, n, e = (round(v, 5) for v in bbox)
    sels = [sel for c in categories for sel in CATEGORIES[c][1]]
    if "riviere" in categories:
        sels.append(FORD)
    body = "".join(f"{sel.ql}({s},{w},{n},{e});" for sel in sels)
    return f"[out:json][timeout:90];({body});out geom;"


def bbox_around(points: list[TrackPoint], margin_m: float) -> tuple[float, float, float, float]:
    lats = [p.lat for p in points]
    lons = [p.lon for p in points]
    dlat = margin_m / 111_000
    dlon = margin_m / (111_000 * max(0.1, math.cos(math.radians(sum(lats) / len(lats)))))
    w, e = lon_bounds(lons, dlon)  # w > e si l'emprise traverse l'antiméridien (géré par Overpass)
    return min(lats) - dlat, w, max(lats) + dlat, e


def classify(tags: dict, categories: list[str]) -> tuple[str, str] | None:
    for cat in categories:
        for sel in CATEGORIES[cat][1]:
            typ = sel.match(tags)
            if typ:
                return cat, typ
    return None


def element_geometry(el: dict, proj: LocalProjection) -> BaseGeometry | None:
    if el["type"] == "node":
        x, y = proj.to_xy(el["lat"], el["lon"])
        return Point(x, y)

    def line(coords: list[dict]) -> LineString | None:
        if len(coords) < 2:
            return None
        xs, ys = proj.to_xy([c["lat"] for c in coords], [c["lon"] for c in coords])
        return LineString(zip(xs, ys, strict=True))

    if el["type"] == "way":
        ln = line(el.get("geometry", []))
        if ln is not None and ln.is_closed and len(ln.coords) >= 4 and el["tags"].get("natural") == "water":
            return Polygon(ln.coords)
        return ln
    parts = [line(m.get("geometry", [])) for m in el.get("members", []) if m.get("type") == "way"]
    parts = [p for p in parts if p is not None]
    return MultiLineString(parts) if parts else None


def score(weight: float, tags: dict, distance_m: float, max_detour_m: float) -> float:
    s = weight
    s += 0.15 if tags.get("name") else 0
    s += 0.25 if tags.get("wikidata") or tags.get("wikipedia") else 0
    s += 0.1 if tags.get("image") or tags.get("wikimedia_commons") else 0
    if distance_m > ON_ROUTE_M:
        s *= max(0.3, 1 - 0.7 * distance_m / max(max_detour_m, 1))
    return round(min(1.0, s / 1.5), 2)


def _ele(tags: dict) -> float | None:
    try:
        return float(tags["ele"].replace(",", ".").split()[0])
    except (KeyError, ValueError, IndexError):
        return None


def _poi(
    el: dict,
    cat: str,
    typ: str,
    km: float,
    latlon: tuple[float, float],
    dist: float,
    max_detour_m: float,
    **kw,
) -> Poi:
    tags = el.get("tags", {})
    return Poi(
        km=round(km, 2),
        categorie=cat,
        type=typ,
        nom=tags.get("name"),
        lat=round(latlon[0], 6),
        lon=round(latlon[1], 6),
        distance_m=round(dist),
        detour_m=0 if dist <= ON_ROUTE_M else round(2 * dist),
        score=score(CATEGORIES[cat][0], tags, dist, max_detour_m),
        ele=_ele(tags),
        intermittent=tags.get("intermittent") == "yes" or tags.get("seasonal") == "yes",
        wikidata=tags.get("wikidata"),
        wikipedia=tags.get("wikipedia"),
        osm_id=f"{el['type']}/{el['id']}",
        **kw,
    )


def _points_of(geom: BaseGeometry) -> list[Point]:
    if geom.is_empty:
        return []
    if isinstance(geom, Point):
        return [geom]
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _points_of(g)]
    return [geom.interpolate(0.5, normalized=True)]  # portion commune (chemin le long du ruisseau)


def annotate(
    points: list[TrackPoint], elements: list[dict], categories: list[str], max_detour_m: float = 300.0
) -> list[Poi]:
    """Points notables le long du tracé, triés par km."""
    lats = np.array([p.lat for p in points])
    lons = np.array([p.lon for p in points])
    total_m = float(cumulative_distance(lats, lons)[-1])
    mid = len(points) // 2
    proj = LocalProjection(lats[mid], lons[mid])
    xs, ys = proj.to_xy(lats, lons)
    route = LineString(zip(xs, ys, strict=True))
    to_km = total_m / route.length / 1000 if route.length else 0

    def latlon(p: Point) -> tuple[float, float]:
        la, lo = proj.to_latlon(p.x, p.y)
        return float(la), float(lo)

    fords = [g for el in elements if FORD.match(el.get("tags", {})) and (g := element_geometry(el, proj))]
    pois: list[Poi] = []
    for el in elements:
        tags = el.get("tags", {})
        found = classify(tags, categories)
        if not found:
            continue
        cat, typ = found
        geom = element_geometry(el, proj)
        if geom is None:
            continue
        if cat == "riviere":
            if tags.get("tunnel") in {"culvert", "yes"}:
                continue  # buse sous le chemin : pas un vrai franchissement
            for pt in _points_of(route.intersection(geom)):
                is_ford = any(f.distance(pt) <= FORD_MATCH_M for f in fords)
                pois.append(
                    _poi(
                        el,
                        cat,
                        typ,
                        route.project(pt) * to_km,
                        latlon(pt),
                        0.0,
                        max_detour_m,
                        via="gué" if is_ford else None,
                    )
                )
            continue
        dist = route.distance(geom)
        if dist > max_detour_m:
            continue
        on_route, on_el = nearest_points(route, geom)
        pois.append(_poi(el, cat, typ, route.project(on_route) * to_km, latlon(on_el), dist, max_detour_m))

    return dedupe(sorted(pois, key=lambda p: p.km))


def dedupe(pois: list[Poi]) -> list[Poi]:
    """Fusionne les doublons : même catégorie et même nom (ou même type si anonyme),
    à moins de 300 m l'un de l'autre le long du tracé."""
    kept: list[Poi] = []
    for p in pois:
        twin = next(
            (
                k
                for k in kept
                if k.categorie == p.categorie
                and (k.nom or k.type) == (p.nom or p.type)
                and abs(k.km - p.km) < 0.3
                and (k.nom is not None or k.distance_m > 0)  # deux franchissements anonymes restent distincts
            ),
            None,
        )
        if twin is None:
            kept.append(p)
        elif p.distance_m < twin.distance_m:
            kept[kept.index(twin)] = p
    return kept


def near_point(
    lat: float, lon: float, elements: list[dict], categories: list[str], radius_m: float
) -> list[tuple[Poi, float]]:
    """Points notables autour d'un lieu (pour planifier), avec leur distance au centre."""
    proj = LocalProjection(lat, lon)
    center = Point(0, 0)
    out = []
    for el in elements:
        found = classify(el.get("tags", {}), categories)
        geom = found and element_geometry(el, proj)
        if not found or geom is None:
            continue
        dist = center.distance(geom)
        if dist > radius_m:
            continue
        _, on_el = nearest_points(center, geom)
        la, lo = proj.to_latlon(on_el.x, on_el.y)
        poi = _poi(el, *found, 0.0, (float(la), float(lo)), dist, radius_m)
        out.append((poi, dist))
    # Sans tracé, la distance au centre n'est pas un détour : on note sur l'intérêt seul.
    for poi, _ in out:
        poi.detour_m = 0
        poi.score = score(CATEGORIES[poi.categorie][0], {"name": poi.nom, "wikidata": poi.wikidata}, 0, radius_m)
    return sorted(out, key=lambda pd: -pd[0].score)
