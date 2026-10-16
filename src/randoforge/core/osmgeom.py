"""Géométries OSM (sortie Overpass `out geom`) projetées en mètres, et leur croisement avec le tracé."""

from __future__ import annotations

import re
from functools import cached_property, reduce

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from .geo import LocalProjection, lon_bounds
from .models import TrackPoint
from .terrain import _runs, route_line

AREA_KEYS = {
    "natural": {"scree", "glacier", "wetland", "water"},
    "boundary": {"national_park", "protected_area"},
    "leisure": {"nature_reserve"},
    "landuse": {"military"},
    "military": None,  # toute valeur
}


def is_area(tags: dict) -> bool:
    for key, values in AREA_KEYS.items():
        if key in tags and (values is None or tags[key] in values):
            return True
    return False


def element_geometry(el: dict, proj: LocalProjection) -> BaseGeometry | None:
    """Point, ligne ou surface selon l'élément ; les multipolygones sont reconstruits."""
    if el["type"] == "node":
        x, y = proj.to_xy(el["lat"], el["lon"])
        return Point(x, y)
    if el["type"] == "way":
        ways = [(el.get("geometry", []), "outer")]
    else:
        ways = [(m.get("geometry", []), m.get("role") or "outer") for m in el.get("members", [])]
    lines, inner = [], []
    for coords, role in ways:
        if coords and len(coords) >= 2:
            xs, ys = proj.to_xy([c["lat"] for c in coords], [c["lon"] for c in coords])
            (inner if role == "inner" else lines).append(LineString(np.column_stack([xs, ys])))
    if not lines:
        return None
    if is_area(el.get("tags", {})):
        if el["type"] == "relation":
            # Anneaux extérieurs moins les enclaves (rôle « inner ») : un village exclu du parc reste exclu.
            # Règle pair-impair sur tous les anneaux (extérieurs et enclaves) : un village exclu du parc reste
            # exclu, et une île dans cette enclave redevient dans le parc.
            rings = [Polygon(p.exterior) for p in shapely.polygonize(lines + inner).geoms]
            area = reduce(lambda a, b: a.symmetric_difference(b), rings) if rings else None
            return None if area is None or area.is_empty else area
        else:
            polys = [Polygon(ln.coords) for ln in lines if ln.is_closed and len(ln.coords) >= 4]
        return shapely.union_all(polys) if polys else None
    return shapely.union_all(lines)


class Locator:
    """Positions le long d'une ligne projetée, sans ambiguïté sur un aller-retour : quand le tracé passe deux fois
    au même endroit, c'est le **premier** passage qui compte (ordre de marche)."""

    def __init__(self, line: LineString):
        xy = np.asarray(line.coords)
        self.line = line
        self.segs = shapely.linestrings(np.stack([xy[:-1], xy[1:]], axis=1))
        self.start = np.concatenate([[0.0], np.cumsum(shapely.length(self.segs))[:-1]])
        self.tree = shapely.STRtree(self.segs)

    def _at(self, i: int, geom: BaseGeometry) -> float:
        seg = self.segs[i]
        return float(self.start[i] + seg.project(nearest_points(seg, geom)[0]))

    def first(self, geom: BaseGeometry, tolerance_m: float = 10.0) -> float:
        """Position (m projetés) du premier passage à moins de `tolerance_m` du point le plus proche de `geom`."""
        near = self.tree.query(geom, predicate="dwithin", distance=self.line.distance(geom) + tolerance_m)
        i = int(near.min()) if len(near) else int(np.argmin(shapely.distance(self.segs, geom)))
        return self._at(i, geom)

    def crossings(self, geom: BaseGeometry) -> list[tuple[float, Point]]:
        """Chaque franchissement de `geom` (rivière…) : position et point, un par passage, aller et retour compris."""
        hits = np.sort(self.tree.query(geom, predicate="intersects"))
        out = []
        for run in np.split(hits, np.flatnonzero(np.diff(hits) > 1) + 1) if len(hits) else []:
            i = int(run[0])
            inter = self.segs[i].intersection(geom)
            pt = inter if inter.geom_type == "Point" else inter.representative_point()
            out.append((self._at(i, pt), pt))
        return out


class RouteFrame:
    """Le tracé projeté, prêt pour les croisements géométriques."""

    def __init__(self, points: list[TrackPoint]):
        self.line, self.proj, self.cum = route_line(points)
        xy = np.asarray(self.line.coords)
        self.pts = shapely.points(xy)
        self._proj_cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])

    @cached_property
    def locator(self) -> Locator:
        return Locator(self.line)

    def km_of(self, geom: BaseGeometry) -> float:
        """Position (m, distance géodésique) du point du tracé le plus proche de `geom` ; premier passage si le
        tracé y passe deux fois (aller-retour)."""
        return float(np.interp(self.locator.first(geom), self._proj_cum, self.cum))

    def ranges_on(self, geom: BaseGeometry, within_m: float = 8.0) -> list[tuple[float, float]]:
        """Portions du tracé (m) dans une surface, ou à moins de `within_m` d'une ligne/d'un point."""
        if geom.geom_type in {"Polygon", "MultiPolygon"}:
            mask = shapely.contains(geom, self.pts) | (shapely.distance(geom, self.pts) <= 1.0)
        else:
            mask = shapely.distance(geom, self.pts) <= within_m
        return [(float(self.cum[a]), float(self.cum[b])) for a, b in _runs(mask)]

    def polyline_filter(self, around_m: float, max_coords: int = 150) -> str:
        """Filtre Overpass `around:` sur une polyligne simplifiée du tracé."""
        tol = 5.0
        simple = self.line.simplify(tol)
        while len(simple.coords) > max_coords:
            tol *= 2
            simple = self.line.simplify(tol)
        xs, ys = zip(*simple.coords, strict=True)
        lats, lons = self.proj.to_latlon(np.array(xs), np.array(ys))
        coords = ",".join(f"{la:.6f},{lo:.6f}" for la, lo in zip(lats, lons, strict=True))
        return f"around:{around_m + tol:.0f},{coords}"

    def bbox(self, margin_m: float = 0.0) -> str:
        lats, lons = self.proj.to_latlon(*np.asarray(self.line.coords).T)
        dlat = margin_m / 111_000
        dlon = margin_m / (111_000 * max(0.1, np.cos(np.radians(np.mean(lats)))))
        w, e = lon_bounds(lons, dlon)
        return f"{lats.min() - dlat:.5f},{w:.5f},{lats.max() + dlat:.5f},{e:.5f}"


# Rôles d'une relation de randonnée qui ne font pas partie du tracé principal.
SIDE_ROLES = {"alternative", "excursion", "approach", "connection", "link", "guidepost", "start", "stop"}
JOIN_TOLERANCE_M = 30.0  # deux chemins OSM consécutifs sont censés se toucher


def _chain(ways: list[list[tuple[float, float]]], flip_first: bool) -> tuple[list[tuple[float, float]], list[float]]:
    """Chemins mis bout à bout ; renvoie le tracé et tous les raccords (m), petits compris."""
    from .geo import distance_m

    line = list(ways[0][::-1] if flip_first else ways[0])
    joins: list[float] = []
    for way in ways[1:]:
        to_start, to_end = distance_m(line[-1], way[0]), distance_m(line[-1], way[-1])
        seg, gap = (way[::-1], to_end) if to_end < to_start else (way, to_start)
        joins.append(gap)
        line.extend(seg[1:] if gap < 1 else seg)
    return line, joins


def _coords(member: dict) -> list[tuple[float, float]]:
    return [
        (c["lat"], c["lon"])
        for c in member.get("geometry") or []
        if c and c.get("lat") is not None and c.get("lon") is not None
    ]


def chain_route_relation(rel: dict) -> tuple[list[tuple[float, float]], list[str]]:
    """Met bout à bout les chemins d'une relation OSM `route=hiking` (sortie `out geom`).

    Les chemins sont pris dans l'ordre de la relation et retournés si besoin. « backward » veut dire « parcouru à
    contresens du dessin » : c'est soit la seule voie (gardée), soit la branche retour d'une section dédoublée
    (écartée). Entre ces variantes et les deux sens du premier chemin, on garde celle qui laisse le moins de trous,
    tous raccords comptés ; à égalité, tous les chemins et le sens du dessin. Renvoie le tracé (lat, lon) et des
    avertissements. Lève ValueError si aucun tracé n'est exploitable.
    """
    members = rel.get("members", [])
    main = [m for m in members if m.get("type") == "way" and (m.get("role") or "") not in SIDE_ROLES]
    every = [(w, m.get("role") or "") for m in main if len(w := _coords(m)) >= 2]
    sub_relations = sum(1 for m in members if m.get("type") == "relation")
    if not every:
        if sub_relations:
            raise ValueError("Itinéraire découpé en sous-itinéraires (étapes) : importer une étape à la fois.")
        raise ValueError("Relation OSM sans chemin exploitable.")
    variants = [([w for w, _ in every], False)]
    if any(r == "backward" for _, r in every) and any(r != "backward" for _, r in every):
        variants.append(([w for w, r in every if r != "backward"], True))
    best = None
    for ways, dropped in variants:
        for flip in (False, True):
            line, joins = _chain(ways, flip)
            key = (round(sum(joins), 1), dropped, flip)
            if best is None or key < best[0]:
                best = (key, line, joins, dropped)
    _, line, joins, dropped_backward = best
    gaps = [g for g in joins if g > JOIN_TOLERANCE_M]
    warnings = []
    if gaps:
        warnings.append(
            f"Relation OSM incomplète ou désordonnée : {len(gaps)} saut(s) entre chemins (max {max(gaps):.0f} m), "
            "reliés en ligne droite. Vérifier le tracé (data_quality) ou le reconstruire avec route_between."
        )
    side = sum(1 for m in members if m.get("type") == "way" and (m.get("role") or "") in SIDE_ROLES)
    if side:
        warnings.append(f"{side} chemin(s) de variante ou d'accès ignoré(s) : seul le tracé principal est importé.")
    if dropped_backward:
        warnings.append("Sections à sens unique (aller/retour différents) : seul le sens aller est importé.")
    if sub_relations:
        warnings.append(
            f"{sub_relations} sous-itinéraire(s) de la relation non importé(s) : tracé possiblement incomplet."
        )
    return line, warnings


def declared_values(tags: dict) -> dict[str, float]:
    """Distance et D+ déclarés dans une relation OSM (comparés aux nôtres, règle N5).

    Tout format douteux est ignoré plutôt que mal lu : unité autre que km/m, « 12.500 » (séparateur de milliers ou
    décimale ?), D+ non entier.
    """
    out: dict[str, float] = {}
    raw = tags.get("distance", "")
    if not re.search(r"\d[.,]\d{3}(?!\d)", raw) and (m := re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(km|m)?\s*", raw)):
        out["distance_m"] = float(m[1].replace(",", ".")) * (1 if m[2] == "m" else 1000)
    if m := re.fullmatch(r"\s*(\d+)\s*(m)?\s*", tags.get("ascent", "")):
        out["d_plus_m"] = float(m[1])
    return out
