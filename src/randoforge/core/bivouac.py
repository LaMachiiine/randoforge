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
from .geo import GEOD, cumulative_distance, distance_m, interp_lon
from .models import AreaCrossing, BivouacSpot, Poi, TechnicalPassage, TrackPoint, WaySegment
from .osmgeom import RouteFrame

SAMPLE_EVERY_M = 250.0
PROBE_M = 15.0
FLAT_PCT = 8.0
WATER_MAX_M = 500.0
ROAD_MIN_M = 300.0
MAX_DETOUR_M = 500.0
AREA_DETOUR_M = 800.0  # camping ou aire décrits par leur surface : mesurés depuis le centre (~500 m du bord)
NIGHT_MARGIN_KM = (4.0, 10.0)  # bornes de la portion de début et de fin de parcours où l'on ne dort pas
NIGHT_NEAR_KM = 3.0  # étapes planifiées : emplacements utiles à moins de 3 km d'une nuit prévue
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
    lats = np.array([p.lat for p in points])
    lons = np.array([p.lon for p in points])
    cum = cumulative_distance(lats, lons)
    ms = np.arange(SAMPLE_EVERY_M, cum[-1] - SAMPLE_EVERY_M / 2, SAMPLE_EVERY_M)
    c_lat, c_lon = np.interp(ms, cum, lats), interp_lon(ms, cum, lons)
    # Les 4 voisins de tous les candidats en un seul calcul géodésique (N, E, S, O).
    n_lon, n_lat, _ = GEOD.fwd(np.repeat(c_lon, 4), np.repeat(c_lat, 4), np.tile([0, 90, 180, 270], len(ms)),
                               np.full(4 * len(ms), PROBE_M))  # fmt: skip
    candidates = [(float(m), float(la), float(lo)) for m, la, lo in zip(ms, c_lat, c_lon, strict=True)]
    probes: list[tuple[float, float]] = []
    for i, (_, la, lo) in enumerate(candidates):
        probes.append((la, lo))
        probes.extend(zip(n_lat[4 * i : 4 * i + 4].tolist(), n_lon[4 * i : 4 * i + 4].tolist(), strict=True))
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
    waters += [(r["lat"], r["lon"]) for r in refuges if r["type"] == "point d'eau" and not unusable(r)]
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
        # La requête OSM peut déborder (simplification du tracé) ; une surface est mesurée depuis son centre.
        if d > (MAX_DETOUR_M if el.get("type") == "node" else AREA_DETOUR_M):
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
        if unusable(r):
            continue  # détruit, inutilisable ou tari : jamais proposé
        m, d = place(r["lat"], r["lon"])
        if d > MAX_DETOUR_M:
            continue
        warnings, forbidden = _legal_warnings(areas, m / 1000)
        if label.startswith("abri naturel"):
            warnings += CAVE_WARNINGS
        closed = is_closed(r)
        if closed:
            warnings.append(f"Signalé « {r['etat']} » sur refuges.info : vérifier avant de compter dessus")
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
                score=0.3 if forbidden or closed else 0.85,
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


UNUSABLE_STATES = ("détruit", "inutilisable", "tari")  # refuges.info : jamais proposés ni comptés comme eau
CLOSED_STATES = ("fermé", "clés à récupérer", "contact préalable")


def unusable(point: dict) -> bool:
    return any(w in (point.get("etat") or "").lower() for w in UNUSABLE_STATES)


def is_closed(point: dict) -> bool:
    return any(w in (point.get("etat") or "").lower() for w in CLOSED_STATES)


def night_window(total_km: float) -> tuple[float, float]:
    """Portion du parcours où une nuit a du sens : ni juste après le départ ni juste avant l'arrivée
    (un quart de la distance de chaque côté, entre 4 et 10 km)."""
    margin = min(NIGHT_MARGIN_KM[1], max(NIGHT_MARGIN_KM[0], 0.25 * total_km))
    if total_km - margin < margin:  # parcours court : la moitié centrale
        return 0.25 * total_km, 0.75 * total_km
    return margin, total_km - margin


def useful_for_night(spots: list[BivouacSpot], total_km: float, stages: list | None = None) -> list[BivouacSpot]:
    """Emplacements placés logiquement pour une nuit ; si des étapes sont planifiées, ceux proches d'une nuit
    prévue. Les autres restent connus (plan_stages peut s'en servir) mais ne sont ni proposés ni affichés."""
    lo, hi = night_window(total_km)
    keep = [b for b in spots if lo <= b.km <= hi]
    nights = [s.km_fin for s in (stages or [])[:-1]]
    if nights:
        keep = [b for b in keep if any(abs(b.km - n) <= NIGHT_NEAR_KM for n in nights)]
    return keep
