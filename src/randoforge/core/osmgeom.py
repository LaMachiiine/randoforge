"""Géométries OSM (sortie Overpass `out geom`) projetées en mètres, et leur croisement avec le tracé."""

from __future__ import annotations

from functools import reduce

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


class RouteFrame:
    """Le tracé projeté, prêt pour les croisements géométriques."""

    def __init__(self, points: list[TrackPoint]):
        self.line, self.proj, self.cum = route_line(points)
        xy = np.asarray(self.line.coords)
        self.pts = shapely.points(xy)
        self._proj_cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])

    def km_of(self, geom: BaseGeometry) -> float:
        """Position (m, distance géodésique) du point du tracé le plus proche de `geom`."""
        return float(np.interp(self.line.project(nearest_points(self.line, geom)[0]), self._proj_cum, self.cum))

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


def chain_route_relation(rel: dict) -> tuple[list[tuple[float, float]], list[str]]:
    """Met bout à bout les chemins d'une relation OSM `route=hiking` (sortie `out geom`).

    Les chemins sont pris dans l'ordre de la relation et retournés si besoin. Renvoie le tracé (lat, lon) et des
    avertissements (variantes ignorées, trous entre chemins). Lève ValueError si aucun tracé n'est exploitable.
    """
    from .geo import distance_m

    members = rel.get("members", [])
    ways = [
        [(c["lat"], c["lon"]) for c in m.get("geometry") or [] if c]
        for m in members
        if m.get("type") == "way" and (m.get("role") or "") not in SIDE_ROLES
    ]
    ways = [w for w in ways if len(w) >= 2]
    skipped = sum(1 for m in members if m.get("type") == "way" and (m.get("role") or "") in SIDE_ROLES)
    if not ways:
        if any(m.get("type") == "relation" for m in members):
            raise ValueError("Itinéraire découpé en sous-itinéraires (étapes) : importer une étape à la fois.")
        raise ValueError("Relation OSM sans chemin exploitable.")
    line = list(ways[0])
    gaps: list[float] = []
    for i, way in enumerate(ways[1:]):
        ends = {
            "fin→début": (distance_m(line[-1], way[0]), False, False),
            "fin→fin": (distance_m(line[-1], way[-1]), False, True),
        }
        if i == 0:  # le premier chemin peut lui-même être à l'envers
            ends["début→début"] = (distance_m(line[0], way[0]), True, False)
            ends["début→fin"] = (distance_m(line[0], way[-1]), True, True)
        gap, flip_line, flip_way = min(ends.values())
        if flip_line:
            line.reverse()
        seg = way[::-1] if flip_way else way
        if gap > JOIN_TOLERANCE_M:
            gaps.append(gap)
        line.extend(seg[1:] if gap < 1 else seg)
    warnings = []
    if gaps:
        warnings.append(
            f"Relation OSM incomplète ou désordonnée : {len(gaps)} saut(s) entre chemins (max {max(gaps):.0f} m), "
            "reliés en ligne droite. Vérifier le tracé (data_quality) ou le reconstruire avec route_between."
        )
    if skipped:
        warnings.append(f"{skipped} chemin(s) de variante ou d'accès ignoré(s) : seul le tracé principal est importé.")
    return line, warnings
