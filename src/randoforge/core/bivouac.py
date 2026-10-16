"""Emplacements de bivouac et hébergements le long du tracé.

Trois sources : OSM (aires de bivouac, cabanes, refuges), refuges.info, et emplacements
*calculés* (terrain plat, eau proche, loin des routes) présentés comme pistes à vérifier.
Aucun appel réseau ici : la pente autour des points candidats est fournie par l'appelant.
"""

from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Point

from .areas import area_at
from .geo import destination_points, distance_m
from .models import AreaCrossing, BivouacSpot, Poi, TechnicalPassage, TrackPoint, WaySegment
from .osmgeom import RouteFrame

SAMPLE_EVERY_M = 250.0
PROBE_M = 15.0
FLAT_PCT = 8.0
WATER_MAX_M = 500.0
ROAD_MIN_M = 300.0
MAX_DETOUR_M = 500.0
ROADS = {"primary", "secondary", "tertiary", "unclassified", "residential", "trunk", "service"}
REFUGES_TYPES = {
    "cabane non gardée": "cabane",
    "refuge gardé": "refuge gardé",
    "gîte d'étape": "gîte",
    "abri naturel": "abri naturel (grotte, abri sous roche)",
}
# Types qui offrent un toit ou une paroi (bivouac abrité)
SHELTERED = {
    "cabane",
    "refuge gardé",
    "gîte",
    "refuge",
    "abri",
    "abri sous roche",
    "grotte",
    "abri naturel (grotte, abri sous roche)",
}
CAVE_WARNINGS = [
    "Abri naturel / grotte : vérifier sur place le risque de crue et de chute de pierres",
    "Ne pas déranger la faune (chauves-souris protégées) ; certaines grottes sont fermées ou réglementées",
]
WATER_CATEGORIES = {"eau", "lac", "cascade"}


def build_query(points: list[TrackPoint]) -> str:
    around = RouteFrame(points).polyline_filter(MAX_DETOUR_M)
    return (
        "[out:json][timeout:90];("
        f'nwr({around})["tourism"="camp_site"];'
        f'nwr({around})["tourism"~"^(wilderness_hut|alpine_hut)$"];'
        f'nwr({around})["amenity"="shelter"]["shelter_type"~"^(basic_hut|weather_shelter|lean_to|rock_shelter)$"];'
        f'node({around})["natural"="cave_entrance"];'
        ");out center tags;"
    )


def probe_points(points: list[TrackPoint]) -> tuple[list[tuple[float, float, float]], list[tuple[float, float]]]:
    """Points candidats tous les 250 m (m, lat, lon) et, pour chacun, centre + 4 points à ±15 m (N, E, S, O)."""
    frame = RouteFrame(points)
    total = frame.cum[-1]
    candidates = []
    probes: list[tuple[float, float]] = []
    lats = np.array([p.lat for p in points])
    lons = np.array([p.lon for p in points])
    for m in np.arange(SAMPLE_EVERY_M, total - SAMPLE_EVERY_M / 2, SAMPLE_EVERY_M):
        lat, lon = float(np.interp(m, frame.cum, lats)), float(np.interp(m, frame.cum, lons))
        candidates.append((float(m), lat, lon))
        probes.append((lat, lon))
        probes.extend(destination_points(lat, lon, [0, 90, 180, 270], PROBE_M))
    return candidates, probes


def slope_from_probes(elevations: list[float | None]) -> list[float | None]:
    """Pente max (%) autour de chaque candidat, à partir de 5 altitudes (centre, N, E, S, O)."""
    out = []
    for i in range(0, len(elevations), 5):
        c, *around = elevations[i : i + 5]
        if c is None or any(e is None for e in around):
            out.append(None)
        else:
            out.append(round(max(abs(e - c) for e in around) / PROBE_M * 100, 1))
    return out


def _road_distance(m: float, segments: list[WaySegment], scale: float) -> float:
    best = math.inf
    for s in segments:
        if s.tags.get("highway") in ROADS:
            a, b = s.start_m * scale, s.end_m * scale
            best = min(best, 0 if a <= m <= b else min(abs(m - a), abs(m - b)))
    return best


def _water_distance(lat: float, lon: float, waters: list[tuple[float, float]]) -> float | None:
    if not waters:
        return None
    return min(distance_m((lat, lon), w) for w in waters)


def _hazard_ranges(technical: list[TechnicalPassage]) -> list[tuple[float, float]]:
    return [
        (t.km * 1000 - 50, t.km * 1000 + t.longueur_m + 50)
        for t in technical
        if {"pierrier", "glacier", "danger"} & set(t.types)
    ]


def _legal_warnings(areas: list[AreaCrossing], km: float) -> tuple[list[str], bool]:
    warnings, forbidden = [], False
    for a in area_at(areas, km):
        if a.bivouac == "interdit":
            forbidden = True
            warnings.append(f"Bivouac probablement interdit ({a.kind}{' ' + a.nom if a.nom else ''})")
        elif a.bivouac == "réglementé":
            warnings.append(f"Bivouac réglementé ({a.kind}{' ' + a.nom if a.nom else ''}) : vérifier le règlement")
    return warnings, forbidden


def find_spots(
    points: list[TrackPoint],
    segments: list[WaySegment],
    engine_distance_m: float | None,
    candidates: list[tuple[float, float, float]],
    slopes: list[float | None],
    osm_elements: list[dict],
    refuges: list[dict],
    pois: list[Poi],
    areas: list[AreaCrossing],
    technical: list[TechnicalPassage],
) -> list[BivouacSpot]:
    frame = RouteFrame(points)
    scale = frame.cum[-1] / engine_distance_m if engine_distance_m else 1.0
    waters = [(p.lat, p.lon) for p in pois if p.categorie in WATER_CATEGORIES]
    waters += [(p.lat, p.lon) for p in pois if p.categorie == "riviere" and not p.intermittent]
    waters += [(r["lat"], r["lon"]) for r in refuges if r["type"] == "point d'eau"]
    hazards = _hazard_ranges(technical)
    eles = [p.ele for p in points]

    def place(lat: float, lon: float) -> tuple[float, float]:
        x, y = frame.proj.to_xy(lat, lon)
        pt = Point(x, y)
        return frame.km_of(pt), frame.line.distance(pt)

    spots: list[BivouacSpot] = []

    # 1. Hébergements et aires cartographiés (OSM)
    for el in osm_elements:
        tags = el.get("tags", {})
        c = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
        if c.get("lat") is None:
            continue
        m, d = place(c["lat"], c["lon"])
        if d > MAX_DETOUR_M:  # la requête OSM peut déborder (tolérance de simplification du tracé)
            continue
        kind = (
            tags.get("tourism")
            or tags.get("shelter_type")
            or ("cave" if tags.get("natural") == "cave_entrance" else "abri")
        )
        label = {
            "camp_site": "aire de bivouac / camping",
            "wilderness_hut": "cabane",
            "alpine_hut": "refuge",
            "basic_hut": "abri",
            "weather_shelter": "abri",
            "lean_to": "abri",
            "rock_shelter": "abri sous roche",
            "cave": "grotte",
        }.get(kind, kind)
        if kind == "camp_site" and tags.get("backcountry") != "yes" and tags.get("camp_site") != "basic":
            label = "camping"
        warnings, forbidden = _legal_warnings(areas, m / 1000)
        if label in {"grotte", "abri sous roche"}:
            warnings += CAVE_WARNINGS
        spots.append(
            BivouacSpot(
                km=round(m / 1000, 2),
                abrite=label in SHELTERED,
                lat=c["lat"],
                lon=c["lon"],
                source="OSM",
                type=label,
                nom=tags.get("name"),
                detour_m=round(2 * d),
                score=0.9 if not forbidden else 0.3,
                eau_m=_water_distance(c["lat"], c["lon"], waters),
                avertissements=warnings,
            )
        )

    # 2. refuges.info
    for r in refuges:
        label = REFUGES_TYPES.get(r["type"]) or ("emplacement de bivouac" if "bivouac" in r["type"] else None)
        if not label:
            continue
        m, d = place(r["lat"], r["lon"])
        if d > MAX_DETOUR_M:
            continue
        warnings, forbidden = _legal_warnings(areas, m / 1000)
        if label.startswith("abri naturel"):
            warnings += CAVE_WARNINGS
        spots.append(
            BivouacSpot(
                km=round(m / 1000, 2),
                abrite=label in SHELTERED,
                lat=r["lat"],
                lon=r["lon"],
                source="refuges.info",
                type=label,
                nom=r["nom"],
                detour_m=round(2 * d),
                alt=r.get("alt"),
                places=r.get("places"),
                lien=r.get("lien"),
                eau_m=_water_distance(r["lat"], r["lon"], waters),
                score=0.85 if not forbidden else 0.3,
                avertissements=warnings,
            )
        )

    # 3. Emplacements calculés
    best_by_km: dict[int, BivouacSpot] = {}
    for (m, lat, lon), slope in zip(candidates, slopes, strict=True):
        if slope is None or slope > FLAT_PCT:
            continue
        if any(a <= m <= b for a, b in hazards):
            continue
        road = _road_distance(m, segments, scale) if segments else None  # tracé importé : routes inconnues
        if road is not None and road < ROAD_MIN_M:
            continue
        water = _water_distance(lat, lon, waters)
        warnings, forbidden = _legal_warnings(areas, m / 1000)
        if forbidden:
            continue
        score = 0.5 * (1 - slope / FLAT_PCT) + 0.3 * (
            1 - min(water, WATER_MAX_M) / WATER_MAX_M if water is not None else 0
        )
        if road is not None:
            score += 0.2 * min(road, 2000) / 2000
        if water is None or water > WATER_MAX_M:
            warnings.append("Pas de point d'eau connu à moins de 500 m : prévoir l'eau")
        if road is None:
            warnings.append("Emplacement calculé (terrain plat ; distance aux routes inconnue) : à vérifier sur place")
        else:
            warnings.append("Emplacement calculé (terrain plat, loin des routes) : à vérifier sur place")
        alt = float(np.interp(m, frame.cum, [e if e is not None else np.nan for e in eles]))
        spot = BivouacSpot(
            km=round(m / 1000, 2),
            lat=round(lat, 6),
            lon=round(lon, 6),
            source="calculé",
            type="emplacement possible",
            pente_pct=slope,
            eau_m=round(water) if water is not None else None,
            alt=None if math.isnan(alt) else round(alt),
            score=round(score * 0.8, 2),
            avertissements=warnings,
        )
        key = int(m // 1000)  # un seul emplacement calculé par km : le meilleur
        if key not in best_by_km or spot.score > best_by_km[key].score:
            best_by_km[key] = spot
    spots.extend(best_by_km.values())
    return sorted(spots, key=lambda s: s.km)
