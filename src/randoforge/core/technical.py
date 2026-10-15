"""Passages techniques le long du tracé (docs/10 - Architecture/Itinérance, bivouac et passages techniques.md).

Combine plusieurs indices indépendants puis fusionne ceux qui se touchent :
- difficulté `sac_scale` des segments fournis par le moteur de routage ;
- pentes fortes calculées sur le MNT ;
- équipements et état du sentier tagués dans OSM (via ferrata, échelles, câbles, visibilité) ;
- pierriers et glaciers traversés, dangers ponctuels (`hazard=*`) ;
- « passages délicats » signalés sur refuges.info.
Aucun appel réseau : les données externes sont fournies par l'appelant.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from shapely.geometry import Point

from .models import SAC_SCALE, TechnicalPassage, TrackPoint, WaySegment
from .osmgeom import RouteFrame, element_geometry
from .terrain import steep_sections

TECH_SAC_MIN = SAC_SCALE.index("demanding_mountain_hiking")  # T3
ON_WAY_M = 8.0
MERGE_GAP_M = 100.0
HAZARD_M = 30.0
REFUGES_M = 60.0  # les points refuges.info sont souvent pointés à quelques dizaines de mètres près
STEEP_PCT = 35.0
SUSPICIOUS_PCT = 60.0  # pente extrême sur un sentier facile : probable artefact du MNT

HAZARDS_FR = {
    "falling_rocks": "chutes de pierres",
    "rockfall": "chutes de pierres",
    "avalanche": "avalanches",
    "landslide": "glissement de terrain",
    "erosion": "érosion",
}


class Clue(BaseModel):
    start_m: float
    end_m: float
    kind: str
    detail: str
    level: int = Field(0, description="Niveau T (1–6) si connu, 0 sinon")
    source: str
    check: bool = False  # à vérifier sur place (indice douteux)


def build_query(points: list[TrackPoint], around_m: float = 15.0) -> str:
    """Requête Overpass le long du tracé + pierriers/glaciers dans l'emprise
    (une surface traversée peut avoir ses bords loin du tracé)."""
    frame = RouteFrame(points)
    around = frame.polyline_filter(around_m)
    hazard_around = frame.polyline_filter(HAZARD_M)
    return (
        "[out:json][timeout:90];("
        f'way({around})["highway"="via_ferrata"];'
        f'way({around})["via_ferrata_scale"];'
        f'way({around})["ladder"="yes"];'
        f'way({around})["highway"="ladder"];'
        f'way({around})["safety_rope"="yes"];'
        f'way({around})["trail_visibility"~"^(bad|horrible|no)$"];'
        f'node({hazard_around})["hazard"];'
        f'nwr["natural"~"^(scree|glacier)$"]({frame.bbox()});'
        ");out geom;"
    )


def _osm_clue(tags: dict, start: float, end: float) -> Clue | None:
    length = end - start
    name = f" ({tags['name']})" if tags.get("name") else ""
    if tags.get("natural") == "glacier":
        return Clue(
            start_m=start,
            end_m=end,
            kind="glacier",
            detail=f"Traversée de glacier{name}",
            level=5,
            source="OSM natural=glacier",
        )
    if tags.get("natural") == "scree":
        if length < 20:
            return None
        return Clue(
            start_m=start,
            end_m=end,
            kind="pierrier",
            detail=f"Pierrier sur ~{length:.0f} m{name}",
            level=3,
            source="OSM natural=scree",
        )
    if tags.get("highway") == "via_ferrata" or "via_ferrata_scale" in tags:
        scale = f" (cotation {tags['via_ferrata_scale']})" if "via_ferrata_scale" in tags else ""
        return Clue(
            start_m=start,
            end_m=end,
            kind="via ferrata",
            detail=f"Via ferrata{scale}{name} : baudrier et longes",
            level=4,
            source="OSM via_ferrata",
        )
    if length < 5 and tags.get("highway") != "ladder":
        return None  # simple croisement d'un chemin voisin
    if tags.get("highway") == "ladder" or tags.get("ladder") == "yes":
        return Clue(start_m=start, end_m=end, kind="échelle", detail=f"Échelle{name}", source="OSM ladder")
    if tags.get("safety_rope") == "yes":
        return Clue(
            start_m=start,
            end_m=end,
            kind="câbles",
            detail=f"Câbles / main courante sur ~{length:.0f} m{name}",
            source="OSM safety_rope",
        )
    if tags.get("trail_visibility") in {"bad", "horrible", "no"}:
        return Clue(
            start_m=start,
            end_m=end,
            kind="sentier peu visible",
            detail=f"Sentier peu visible ({tags['trail_visibility']}) : orientation nécessaire",
            source="OSM trail_visibility",
        )
    return None


def osm_clues(points: list[TrackPoint], elements: list[dict]) -> list[Clue]:
    frame = RouteFrame(points)
    clues: list[Clue] = []
    for el in elements:
        tags = el.get("tags", {})
        geom = element_geometry(el, frame.proj)
        if geom is None:
            continue
        if el["type"] == "node" and "hazard" in tags:
            if frame.line.distance(geom) <= HAZARD_M:
                m = frame.km_of(geom)
                label = HAZARDS_FR.get(tags["hazard"], tags["hazard"])
                clues.append(
                    Clue(start_m=m, end_m=m, kind="danger", detail=f"Danger signalé : {label}", source="OSM hazard")
                )
            continue
        for start, end in frame.ranges_on(geom, ON_WAY_M):
            clue = _osm_clue(tags, start, end)
            if clue:
                clues.append(clue)
    return clues


def refuges_clues(points: list[TrackPoint], refuges: list[dict]) -> list[Clue]:
    """« Passages délicats » de refuges.info proches du tracé."""
    frame = RouteFrame(points)
    clues = []
    for r in refuges:
        if "délicat" not in r.get("type", ""):
            continue
        x, y = frame.proj.to_xy(r["lat"], r["lon"])
        pt = Point(x, y)
        if frame.line.distance(pt) <= REFUGES_M:
            m = frame.km_of(pt)
            clues.append(
                Clue(
                    start_m=m,
                    end_m=m,
                    kind="passage délicat",
                    detail=f"Passage délicat signalé : {r['nom']}",
                    source="refuges.info",
                )
            )
    return clues


def segment_clues(segments: list[WaySegment], scale: float) -> list[Clue]:
    """Portions de difficulté T3+ d'après `sac_scale` ; `scale` aligne les distances du moteur sur les nôtres."""
    clues = []
    for s in segments:
        sac = s.tags.get("sac_scale")
        if sac in SAC_SCALE and SAC_SCALE.index(sac) >= TECH_SAC_MIN:
            lvl = SAC_SCALE.index(sac) + 1
            clues.append(
                Clue(
                    start_m=s.start_m * scale,
                    end_m=s.end_m * scale,
                    kind=f"difficulté T{lvl}",
                    detail=f"Sentier {sac} (T{lvl})",
                    level=lvl,
                    source="OSM sac_scale",
                )
            )
    return clues


def slope_clues(points: list[TrackPoint], segments: list[WaySegment], scale: float) -> list[Clue]:
    def sac_at(m: float) -> str | None:
        for s in segments:
            if s.start_m * scale <= m <= s.end_m * scale:
                return s.tags.get("sac_scale")
        return None

    clues = []
    for sec in steep_sections(points, STEEP_PCT):
        easy = sac_at((sec.start_m + sec.end_m) / 2) == "hiking"
        suspicious = sec.value > SUSPICIOUS_PCT and easy
        detail = f"Pente jusqu'à {sec.value:.0f} % sur ~{sec.end_m - sec.start_m:.0f} m"
        if suspicious:
            detail += " (sentier pourtant classé facile : possible artefact du relief, à vérifier)"
        clues.append(
            Clue(
                start_m=sec.start_m, end_m=sec.end_m, kind="pente forte", detail=detail, source="MNT", check=suspicious
            )
        )
    return clues


def merge(clues: list[Clue]) -> list[TechnicalPassage]:
    passages: list[list[Clue]] = []
    for c in sorted(clues, key=lambda c: c.start_m):
        if passages and c.start_m - max(x.end_m for x in passages[-1]) <= MERGE_GAP_M:
            passages[-1].append(c)
        else:
            passages.append([c])
    out = []
    for group in passages:
        start = min(c.start_m for c in group)
        end = max(c.end_m for c in group)
        lvl = max(c.level for c in group)
        out.append(
            TechnicalPassage(
                km=round(start / 1000, 2),
                longueur_m=round(end - start),
                niveau=f"T{lvl}" if lvl else None,
                types=list(dict.fromkeys(c.kind for c in group)),
                details=list(dict.fromkeys(c.detail for c in group)),
                sources=list(dict.fromkeys(c.source for c in group)),
                # Douteux seulement si tous les indices le sont
                a_verifier=all(c.check for c in group),
            )
        )
    return out


def technical_passages(
    points: list[TrackPoint],
    segments: list[WaySegment],
    elements: list[dict],
    engine_distance_m: float | None,
    refuges: list[dict] | None = None,
) -> list[TechnicalPassage]:
    frame = RouteFrame(points)
    scale = frame.cum[-1] / engine_distance_m if engine_distance_m else 1.0
    clues = (
        segment_clues(segments, scale)
        + slope_clues(points, segments, scale)
        + osm_clues(points, elements)
        + refuges_clues(points, refuges or [])
    )
    return merge(clues)
