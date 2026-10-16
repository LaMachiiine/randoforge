"""Observations de la neige au sol : satellites NASA (MODIS / VIIRS, quotidien, 500 m) et Sentinel-2 (20 m).

- **GIBS** (NASA Global Imagery Browse Services) : couverture neigeuse NDSI quotidienne, tuiles PNG à palette.
  Les pixels sont décodés par la **couleur** de la palette (les index des classes diffèrent selon le satellite).
  Remerciement demandé : « imagery provided by services from NASA's GIBS, part of NASA's ESDIS ».
- **Sentinel-2 L2A** (catalogue public Earth Search, AWS) : classification de scène SCL à 20 m, classe 11 =
  neige/glace ; une image tous les 2 à 5 jours. « Contains modified Copernicus Sentinel data ».

Les deux sont optiques : rien n'est vu sous les nuages ; ils disent si la neige est présente, pas son épaisseur.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from ..http import DAY, CachedHttp

GIBS_URL = "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/{layer}/default/{day}/500m/7/{row}/{col}.png"
GIBS_LAYERS = [
    "MODIS_Terra_NDSI_Snow_Cover",
    "MODIS_Aqua_NDSI_Snow_Cover",
    "VIIRS_NOAA20_NDSI_Snow_Cover",
    "VIIRS_SNPP_NDSI_Snow_Cover",
    "VIIRS_NOAA21_NDSI_Snow_Cover",
]
PIXEL_DEG = 0.5625 / 2**7  # niveau 7 de la grille « 500m » (~490 m)
TILE_PX = 512
TILE_DEG = PIXEL_DEG * TILE_PX
CLOUD, UNKNOWN = -1, -2  # valeurs spéciales ; 0 = sol sans neige ; 1..100 = NDSI de la neige
CLOUD_RGB = (0, 191, 255)

S2_SEARCH = "https://earth-search.aws.element84.com/v1/search"
S2_COLLECTION = "sentinel-2-l2a"
SCL_SNOW, SCL_CLOUDS, SCL_NODATA = {11}, {3, 8, 9, 10}, {0, 1, 2}  # 2 : ombre (relief) → indéterminé


@dataclass
class SnowGrid:
    """Composite de plusieurs jours : pour chaque pixel, la vue la plus récente sans nuage."""

    lat0: float  # bord nord
    lon0: float  # bord ouest
    values: np.ndarray  # int16 : NDSI 0..100, CLOUD, UNKNOWN
    days: np.ndarray  # jour d'observation (ordinal) ou 0
    sources: set[str]

    def index(self, lat: float, lon: float) -> tuple[int, int] | None:
        r, c = int((self.lat0 - lat) / PIXEL_DEG), int((lon - self.lon0) / PIXEL_DEG)
        if 0 <= r < self.values.shape[0] and 0 <= c < self.values.shape[1]:
            return r, c
        return None

    def centers(self) -> tuple[np.ndarray, np.ndarray]:
        rows, cols = self.values.shape
        lats = self.lat0 - (np.arange(rows) + 0.5) * PIXEL_DEG
        lons = self.lon0 + (np.arange(cols) + 0.5) * PIXEL_DEG
        return lats, lons


def _decode(png: bytes) -> np.ndarray:
    """PNG à palette GIBS → valeurs (NDSI 0..100, CLOUD, UNKNOWN), d'après la couleur de chaque index."""
    import warnings

    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile

    with warnings.catch_warnings(), MemoryFile(png) as mem:
        warnings.simplefilter("ignore", NotGeoreferencedWarning)  # tuile PNG sans géoréférence : normal
        ds = mem.open()
        idx = ds.read(1)
        palette = ds.colormap(1)
        ds.close()
    lut = np.full(256, UNKNOWN, dtype=np.int16)
    lut[0] = 0  # sol sans neige
    for i, rgba in palette.items():
        rgb = tuple(rgba[:3])
        if 1 <= i <= 100 and rgb != (0, 0, 0):
            lut[i] = i  # NDSI de la neige, en %
        elif rgb == CLOUD_RGB:
            lut[i] = CLOUD
    return lut[idx]


class GibsSnow:
    name = "satellites MODIS / VIIRS (NASA GIBS)"

    def __init__(self, http: CachedHttp, url: str | None = None):
        self.http = http
        self.url = url or GIBS_URL

    def _tile(self, layer: str, day: date, row: int, col: int) -> np.ndarray | None:
        # Le jour même, l'image s'enrichit au fil des passages : cache court ; ensuite elle est définitive.
        ttl = 3 * 3600 if day >= date.today() - timedelta(days=1) else 60 * DAY
        png = self.http.request_bytes(self.url.format(layer=layer, day=day.isoformat(), row=row, col=col),
                                      ttl_s=ttl, service="Satellites NASA GIBS")  # fmt: skip
        if not png or len(png) < 3000:  # tuile vide (date pas encore traitée)
            return None
        return _decode(png)

    def composite(self, bbox: tuple[float, float, float, float], day: date, days_back: int = 4) -> SnowGrid:
        """Couverture neigeuse du rectangle (sud, ouest, nord, est) : jour `day` puis jours précédents, tous
        satellites ; chaque pixel garde sa vue la plus récente sans nuage."""
        s, w, n, e = bbox
        lat0 = 90 - math.floor((90 - n) / PIXEL_DEG) * PIXEL_DEG
        lon0 = -180 + math.floor((w + 180) / PIXEL_DEG) * PIXEL_DEG
        rows = max(1, math.ceil((lat0 - s) / PIXEL_DEG))
        cols = max(1, math.ceil((e - lon0) / PIXEL_DEG))
        values = np.full((rows, cols), UNKNOWN, dtype=np.int16)
        days = np.zeros((rows, cols), dtype=np.int32)
        sources: set[str] = set()
        r0, c0 = round((90 - lat0) / PIXEL_DEG), round((lon0 + 180) / PIXEL_DEG)  # en pixels globaux
        tiles = {(tr, tc) for tr in range((r0) // TILE_PX, (r0 + rows - 1) // TILE_PX + 1)
                 for tc in range(c0 // TILE_PX, (c0 + cols - 1) // TILE_PX + 1)}  # fmt: skip
        for back in range(days_back + 1):
            d = day - timedelta(days=back)
            for layer in GIBS_LAYERS:
                if not (values < 0).any():
                    return SnowGrid(lat0, lon0, values, days, sources)
                for tr, tc in tiles:
                    tile = self._tile(layer, d, tr, tc)
                    if tile is None:
                        continue
                    # Partie de la tuile qui recouvre la grille demandée.
                    gr0, gc0 = tr * TILE_PX, tc * TILE_PX
                    a, b = max(r0, gr0), min(r0 + rows, gr0 + TILE_PX)
                    c, f = max(c0, gc0), min(c0 + cols, gc0 + TILE_PX)
                    if a >= b or c >= f:
                        continue
                    part = tile[a - gr0 : b - gr0, c - gc0 : f - gc0]
                    target = values[a - r0 : b - r0, c - c0 : f - c0]
                    fill = (target < 0) & (part >= 0)
                    if fill.any():
                        target[fill] = part[fill]
                        days[a - r0 : b - r0, c - c0 : f - c0][fill] = d.toordinal()
                        sources.add(layer.split("_NDSI")[0].replace("_", " "))
                    cloudy = (target == UNKNOWN) & (part == CLOUD)
                    target[cloudy] = CLOUD
        return SnowGrid(lat0, lon0, values, days, sources)


class Sentinel2Snow:
    name = "Sentinel-2 (20 m)"

    def __init__(self, http: CachedHttp, url: str | None = None):
        self.http = http
        self.url = url or S2_SEARCH

    def scene(self, bbox: tuple[float, float, float, float], day: date, days_back: int = 6, max_cloud: float = 60):
        """Images Sentinel-2 récentes (les plus récentes d'abord) couvrant le rectangle (sud, ouest, nord, est)."""
        s, w, n, e = bbox
        body = {
            "collections": [S2_COLLECTION],
            "bbox": [w, s, e, n],
            "datetime": f"{(day - timedelta(days=days_back)).isoformat()}T00:00:00Z/{day.isoformat()}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lt": max_cloud}},
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            "limit": 10,
        }
        res = self.http.request_json(
            "POST", self.url, json_body=body, ttl_s=3 * 3600, service="Sentinel-2 (Earth Search)"
        )
        return res.get("features", [])

    def classes(self, items: list[dict], points: list[tuple[float, float]]) -> tuple[str | None, list[int | None]]:
        """Classe SCL de chaque point pour la date la plus récente couvrant des points : (date, classes)."""
        import rasterio
        from pyproj import Transformer
        from rasterio.env import Env

        out: list[int | None] = [None] * len(points)
        when = None
        with Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
            for item in items:
                day_str = item["properties"]["datetime"][:10]
                if when and day_str != when:
                    break  # une seule date : les autres tuiles du même passage seulement
                href = item["assets"].get("scl", {}).get("href")
                if not href:
                    continue
                with rasterio.open(f"/vsicurl/{href}") as ds:
                    to = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
                    xs, ys = to.transform([p[1] for p in points], [p[0] for p in points])
                    left, bottom, right, top = ds.bounds
                    todo = [i for i, (x, y) in enumerate(zip(xs, ys, strict=True))
                            if out[i] is None and left <= x <= right and bottom <= y <= top]  # fmt: skip
                    if not todo:
                        continue
                    for i, v in zip(todo, ds.sample([(xs[i], ys[i]) for i in todo]), strict=True):
                        out[i] = int(v[0])
                    when = when or day_str
        return when, out
