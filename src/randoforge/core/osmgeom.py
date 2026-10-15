"""Géométries OSM (sortie Overpass `out geom`) projetées en mètres, et leur croisement avec le tracé."""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from .geo import LocalProjection
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
    ways = [el.get("geometry", [])] if el["type"] == "way" else [m.get("geometry", []) for m in el.get("members", [])]
    lines = []
    for coords in ways:
        if coords and len(coords) >= 2:
            xs, ys = proj.to_xy([c["lat"] for c in coords], [c["lon"] for c in coords])
            lines.append(LineString(np.column_stack([xs, ys])))
    if not lines:
        return None
    if is_area(el.get("tags", {})):
        if el["type"] == "relation":
            polys = list(shapely.polygonize(lines).geoms)
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
        return f"{lats.min() - dlat:.5f},{lons.min() - dlon:.5f},{lats.max() + dlat:.5f},{lons.max() + dlon:.5f}"
