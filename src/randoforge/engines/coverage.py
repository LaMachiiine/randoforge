"""Couverture mobile théorique (France) : tuiles vectorielles de la carte « Mon réseau mobile » de l'Arcep.

Service interne de la carte, non documenté (il peut changer sans préavis) ; mêmes données que les fichiers
publiés sous Licence Ouverte (« Arcep – Mon réseau mobile », mise à jour trimestrielle). Couverture **théorique**
déclarée par les opérateurs, à l'extérieur. Niveaux : TBC (très bonne), BC (bonne), CL (limitée).
"""

from __future__ import annotations

import math

from ..http import DAY, CachedHttp

URL = ("https://monreseaumobile.arcep.fr/tileserv/mrm_public.couvertures/{z}/{x}/{y}.pbf"
       "?liste_operateur=%7B20801,20810,20815,20820%7D&liste_techno=%7B2G3G,4G%7D")  # fmt: skip
ZOOM = 12  # tuile de ~7 km : même résultat au point qu'en z14/z16 (vérifié)
EXTENT = 4096
OPERATORS = {20801: "Orange", 20810: "SFR", 20815: "Free", 20820: "Bouygues Telecom"}
ATTRIBUTION = "Arcep – Mon réseau mobile (couverture théorique déclarée par les opérateurs)"


def tile_of(lat: float, lon: float, z: int = ZOOM) -> tuple[int, int, float, float]:
    """Tuile (x, y) et position dans la tuile (0..EXTENT, y vers le bas)."""
    n = 2**z
    fx = (lon + 180) / 360 * n
    lat_r = math.radians(lat)
    fy = (1 - math.asinh(math.tan(lat_r)) / math.pi) / 2 * n
    x, y = int(fx), int(fy)
    return x, y, (fx - x) * EXTENT, (fy - y) * EXTENT


class ArcepCoverage:
    name = "Arcep"

    def __init__(self, http: CachedHttp, url: str | None = None):
        self.http = http
        self.url = url or URL

    def tile(self, x: int, y: int, z: int = ZOOM) -> list[tuple[object, dict]]:
        """Polygones de couverture de la tuile (coordonnées tuile, y vers le bas) avec leurs propriétés."""
        import mapbox_vector_tile
        from shapely.geometry import shape

        data = self.http.request_bytes(self.url.format(z=z, x=x, y=y), ttl_s=30 * DAY, service="Arcep (couverture)")
        if not data:
            return []
        layers = mapbox_vector_tile.decode(data, default_options={"y_coord_down": True})
        out = []
        for layer in layers.values():
            for f in layer.get("features", []):
                try:
                    out.append((shape(f["geometry"]), f.get("properties", {})))
                except (KeyError, ValueError, TypeError):
                    continue
        return out
