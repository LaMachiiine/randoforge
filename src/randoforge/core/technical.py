"""Passages techniques le long du tracé (docs/10 - Architecture/Itinérance, bivouac et passages techniques.md).

Combine plusieurs indices indépendants puis fusionne ceux qui se touchent :
- difficulté `sac_scale` des segments fournis par le moteur de routage ;
- pentes fortes calculées sur le MNT ;
- équipements et état du sentier tagués dans OSM (via ferrata, échelles, câbles, visibilité) ;
- pierriers et glaciers traversés, dangers ponctuels (`hazard=*`).
Aucun appel réseau : les éléments Overpass sont fournis par l'appelant.
"""

from __future__ import annotations

import numpy as np
import shapely
from pydantic import BaseModel, Field
from shapely.geometry import LineString, Point, Polygon

from .models import SAC_SCALE, TechnicalPassage, TrackPoint, WaySegment
from .terrain import _runs, route_line, steep_sections

T_LEVELS = {s: f"T{i + 1}" for i, s in enumerate(SAC_SCALE)}
TECH_SAC_MIN = SAC_SCALE.index("demanding_mountain_hiking")  # T3
ON_WAY_M = 8.0
MERGE_GAP_M = 100.0
HAZARD_M = 30.0
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


def build_query(points: list[TrackPoint], around_m: float = 15.0, max_coords: int = 150) -> str:
    """Requête Overpass le long du tracé (filtre `around` sur une polyligne simplifiée) +
    pierriers/glaciers dans l'emprise (un polygone traversé peut avoir ses bords loin du tracé)."""
    line, proj, _ = route_line(points)
    tol = 5.0
    simple = line.simplify(tol)
    while len(simple.coords) > max_coords:
        tol *= 2
        simple = line.simplify(tol)
    xs, ys = zip(*simple.coords, strict=True)
    lats, lons = proj.to_latlon(np.array(xs), np.array(ys))
    poly = ",".join(f"{la:.6f},{lo:.6f}" for la, lo in zip(lats, lons, strict=True))
    around = f"around:{around_m + tol:.0f},{poly}"
    lat_all = [p.lat for p in points]
    lon_all = [p.lon for p in points]
    bbox = f"{min(lat_all):.5f},{min(lon_all):.5f},{max(lat_all):.5f},{max(lon_all):.5f}"
    return (
        "[out:json][timeout:90];("
        f'way({around})["highway"="via_ferrata"];'
        f'way({around})["via_ferrata_scale"];'
        f'way({around})["ladder"="yes"];'
        f'way({around})["highway"="ladder"];'
        f'way({around})["safety_rope"="yes"];'
        f'way({around})["trail_visibility"~"^(bad|horrible|no)$"];'
        f'node(around:{HAZARD_M + tol:.0f},{poly})["hazard"];'
        f'nwr["natural"~"^(scree|glacier)$"]({bbox});'
        ");out geom;"
    )


def _geometry(el: dict, proj):
    if el["type"] == "node":
        x, y = proj.to_xy(el["lat"], el["lon"])
        return Point(x, y)
    rings = []
    ways = [el.get("geometry", [])] if el["type"] == "way" else [m.get("geometry", []) for m in el.get("members", [])]
    for coords in ways:
        if len(coords) >= 2:
            xs, ys = proj.to_xy([c["lat"] for c in coords], [c["lon"] for c in coords])
            rings.append(LineString(np.column_stack([xs, ys])))
    if not rings:
        return None
    if el["tags"].get("natural") in {"scree", "glacier"}:
        polys = [Polygon(r.coords) for r in rings if r.is_closed and len(r.coords) >= 4]
        if el["type"] == "relation":
            # Multipolygone : on reconstruit les surfaces à partir des membres
            polys = list(shapely.polygonize(rings).geoms) or polys
        return shapely.union_all(polys) if polys else None
    return shapely.union_all(rings)


def _ranges_on(geom, pts_xy, cum: np.ndarray, within_m: float) -> list[tuple[float, float]]:
    """Portions du tracé (en m) à moins de `within_m` de la géométrie (ou à l'intérieur pour une surface)."""
    if isinstance(geom, Polygon) or geom.geom_type == "MultiPolygon":
        mask = shapely.contains(geom, pts_xy) | (shapely.distance(geom, pts_xy) <= 1.0)
    else:
        mask = shapely.distance(geom, pts_xy) <= within_m
    return [(float(cum[a]), float(cum[b])) for a, b in _runs(mask)]


def osm_clues(points: list[TrackPoint], elements: list[dict]) -> list[Clue]:
    line, proj, cum = route_line(points)
    xy = np.asarray(line.coords)
    pts_xy = shapely.points(xy)
    proj_cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    clues: list[Clue] = []
    for el in elements:
        tags = el.get("tags", {})
        geom = _geometry(el, proj)
        if geom is None:
            continue
        name = f" ({tags['name']})" if tags.get("name") else ""
        if el["type"] == "node" and "hazard" in tags:
            d = line.distance(geom)
            if d <= HAZARD_M:
                m = float(np.interp(line.project(geom), proj_cum, cum))
                label = HAZARDS_FR.get(tags["hazard"], tags["hazard"])
                clues.append(
                    Clue(start_m=m, end_m=m, kind="danger", detail=f"Danger signalé : {label}", source="OSM hazard")
                )
            continue
        for start, end in _ranges_on(geom, pts_xy, cum, ON_WAY_M):
            length = end - start
            if tags.get("natural") == "glacier":
                clues.append(
                    Clue(
                        start_m=start,
                        end_m=end,
                        kind="glacier",
                        detail=f"Traversée de glacier{name}",
                        level=5,
                        source="OSM natural=glacier",
                    )
                )
            elif tags.get("natural") == "scree":
                if length >= 20:
                    clues.append(
                        Clue(
                            start_m=start,
                            end_m=end,
                            kind="pierrier",
                            detail=f"Pierrier sur ~{length:.0f} m{name}",
                            level=3,
                            source="OSM natural=scree",
                        )
                    )
            elif tags.get("highway") == "via_ferrata" or "via_ferrata_scale" in tags:
                scale = f" (cotation {tags['via_ferrata_scale']})" if "via_ferrata_scale" in tags else ""
                clues.append(
                    Clue(
                        start_m=start,
                        end_m=end,
                        kind="via ferrata",
                        detail=f"Via ferrata{scale}{name} : baudrier et longes",
                        level=4,
                        source="OSM via_ferrata",
                    )
                )
            elif length < 5 and tags.get("highway") not in {"ladder"}:
                continue  # simple croisement d'un chemin voisin
            elif tags.get("highway") == "ladder" or tags.get("ladder") == "yes":
                clues.append(
                    Clue(start_m=start, end_m=end, kind="échelle", detail=f"Échelle{name}", source="OSM ladder")
                )
            elif tags.get("safety_rope") == "yes":
                clues.append(
                    Clue(
                        start_m=start,
                        end_m=end,
                        kind="câbles",
                        detail=f"Câbles / main courante sur ~{length:.0f} m{name}",
                        source="OSM safety_rope",
                    )
                )
            elif tags.get("trail_visibility") in {"bad", "horrible", "no"}:
                clues.append(
                    Clue(
                        start_m=start,
                        end_m=end,
                        kind="sentier peu visible",
                        detail=f"Sentier peu visible ({tags['trail_visibility']}) : orientation nécessaire",
                        source="OSM trail_visibility",
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
    points: list[TrackPoint], segments: list[WaySegment], elements: list[dict], engine_distance_m: float | None
) -> list[TechnicalPassage]:
    _, _, cum = route_line(points)
    scale = cum[-1] / engine_distance_m if engine_distance_m else 1.0
    clues = segment_clues(segments, scale) + slope_clues(points, segments, scale) + osm_clues(points, elements)
    return merge(clues)
