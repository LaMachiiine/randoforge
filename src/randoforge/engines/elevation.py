"""Fournisseurs d'altitude (voir docs/20 - Plan/Décisions/ADR-003 - Altimétrie mondiale.md)."""

from __future__ import annotations

import math
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np

from ..http import CachedHttp, HttpError

LatLon = tuple[float, float]

_RASTERIO_LOCK = threading.Lock()


def load_rasterio() -> None:
    """Importe rasterio (lent, donc à la demande) une seule fois, sous verrou : importé en même temps depuis deux
    fils (analyses en parallèle), il échoue à moitié initialisé (« cannot import name tastes_like_gdal »)."""
    with _RASTERIO_LOCK:
        import pyproj  # noqa: F401
        import rasterio  # noqa: F401
        import rasterio.env
        import rasterio.errors
        import rasterio.io
        import rasterio.merge
        import rasterio.warp
        import rasterio.windows  # noqa: F401


class IgnElevation:
    """API Altimétrie de la Géoplateforme IGN : RGE ALTI 1–5 m, France uniquement.

    Hors couverture, l'API renvoie -99999 : on le traduit en None pour passer la main au suivant.
    """

    name = "IGN RGE ALTI"
    URL = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
    CHUNK = 1000  # testé jusqu'à 5000 en POST

    def __init__(self, http: CachedHttp):
        self.http = http

    def elevations(self, points: list[LatLon]) -> list[float | None]:
        out: list[float | None] = []
        for i in range(0, len(points), self.CHUNK):
            chunk = points[i : i + self.CHUNK]
            body = {
                "lon": "|".join(f"{lon:.6f}" for _, lon in chunk),
                "lat": "|".join(f"{lat:.6f}" for lat, _ in chunk),
                "resource": "ign_rge_alti_wld",
                "zonly": "true",
            }
            res = self.http.request_json("POST", self.URL, json_body=body, ttl_s=None, service="Altimétrie IGN")
            values = res.get("elevations", [])
            if len(values) != len(chunk):
                raise ValueError(f"Altimétrie IGN : {len(values)} valeurs reçues pour {len(chunk)} points")
            out += [None if v is None or v <= -9999 else float(v) for v in values]
        return out


# Tuile absente (mer) : S3 répond 404, ou 403 sur une clé inexistante. Vérifié par une requête HTTP plutôt que
# d'après le message de GDAL, qui garde en mémoire un échec réseau et le présente ensuite comme « does not exist ».
MISSING_STATUS = {403, 404}


def tile_missing(url: str) -> bool:
    """Vrai si le serveur confirme que la tuile n'existe pas ; une panne réseau lève HttpError."""
    try:
        r = httpx.head(url, timeout=15, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise HttpError(f"Copernicus injoignable ({type(exc).__name__})") from exc
    if r.status_code in MISSING_STATUS:
        return True
    if r.status_code >= 400:
        raise HttpError(f"Copernicus : erreur {r.status_code}")
    return False


@dataclass
class DemGrid:
    """Grille d'altitudes en degrés (ligne 0 = bord nord)."""

    z: np.ndarray
    top: float
    left: float
    dlat: float
    dlon: float
    source: str


class CopernicusElevation:
    """Copernicus DEM GLO-30 (30 m, monde entier), tuiles COG lues à distance sur AWS.

    Attention : c'est un modèle de *surface* (canopée, bâtiments inclus), moins fiable en forêt.
    Interpolation bilinéaire entre les 4 pixels voisins.
    """

    name = "Copernicus GLO-30"
    BASE = "https://copernicus-dem-30m.s3.amazonaws.com"

    @staticmethod
    def tile_name(lat: float, lon: float) -> str:
        la, lo = math.floor(lat), math.floor(lon)
        ns = f"{'N' if la >= 0 else 'S'}{abs(la):02d}"
        ew = f"{'E' if lo >= 0 else 'W'}{abs(lo):03d}"
        return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"

    def grid(self, bbox: tuple[float, float, float, float]) -> DemGrid:
        """Altitudes d'un rectangle (sud, ouest, nord, est) en grille (tuiles voisines assemblées) : pour les calculs
        de pente. NaN en mer ou hors données."""
        load_rasterio()
        import rasterio
        from rasterio.env import Env
        from rasterio.errors import RasterioIOError
        from rasterio.merge import merge

        s, w, n, e = bbox
        names = {self.tile_name(la + 0.5, lo + 0.5) for la in range(math.floor(s), math.floor(n) + 1)
                 for lo in range(math.floor(w), math.floor(e) + 1)}  # fmt: skip
        env = Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
            CPL_VSIL_CURL_NON_CACHED=f"/vsicurl/{self.BASE}",
        )
        with env:
            datasets = []
            try:
                for name in sorted(names):
                    url = f"{self.BASE}/{name}/{name}.tif"
                    try:
                        datasets.append(rasterio.open(f"/vsicurl/{url}"))
                    except RasterioIOError:
                        if not tile_missing(url):
                            raise
                if not datasets:
                    raise ValueError("Aucune tuile Copernicus sur cette zone (mer ?).")
                # Résolution de la première tuile (les tuiles au-delà de 50° de latitude sont plus larges en longitude).
                arr, transform = merge(datasets, bounds=(w, s, e, n), res=datasets[0].res, nodata=np.nan,
                                       dtype="float32")  # fmt: skip
            finally:
                for ds in datasets:
                    ds.close()
        return DemGrid(z=arr[0], top=transform.f, left=transform.c, dlat=-transform.e, dlon=transform.a,
                       source=self.name)  # fmt: skip

    def elevations(self, points: list[LatLon]) -> list[float | None]:
        load_rasterio()
        import rasterio
        from rasterio.env import Env
        from rasterio.errors import RasterioIOError

        out: list[float | None] = [None] * len(points)
        by_tile: dict[str, list[int]] = defaultdict(list)
        for i, (lat, lon) in enumerate(points):
            by_tile[self.tile_name(lat, lon)].append(i)

        # Pas de cache GDAL pour ces tuiles : un échec réseau ne doit pas survivre au retour du réseau.
        env = Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
            CPL_VSIL_CURL_NON_CACHED=f"/vsicurl/{self.BASE}",
        )
        with env:
            for tile, idx in by_tile.items():
                url = f"/vsicurl/{self.BASE}/{tile}/{tile}.tif"
                try:
                    ds = rasterio.open(url)
                except RasterioIOError:
                    if tile_missing(f"{self.BASE}/{tile}/{tile}.tif"):
                        continue  # pas de tuile (mer) : on laisse None
                    raise  # la tuile existe : panne de lecture, à ne pas confondre avec « pas de tuile »
                with ds:
                    z = sample_bilinear(ds, [points[i] for i in idx])
                for i, v in zip(idx, z, strict=True):
                    out[i] = None if np.isnan(v) else round(float(v), 2)
        return out


def sample_bilinear(ds, points: list[LatLon]) -> np.ndarray:
    """Altitudes interpolées (bilinéaire) dans un raster ouvert ; NaN hors emprise ou sans donnée.

    Les points (WGS84) sont reprojetés dans le système du raster si besoin.
    """
    load_rasterio()
    from rasterio.windows import Window

    lats = np.array([p[0] for p in points])
    lons = np.array([p[1] for p in points])
    if ds.crs and ds.crs.to_epsg() != 4326:
        from pyproj import Transformer

        xs, ys = Transformer.from_crs("EPSG:4326", ds.crs.to_wkt(), always_xy=True).transform(lons, lats)
    else:
        xs, ys = lons, lats
    cols, rows = ~ds.transform * (np.asarray(xs), np.asarray(ys))
    # Coordonnées relatives aux centres de pixels
    c, r = np.asarray(cols) - 0.5, np.asarray(rows) - 0.5
    c0, r0 = int(np.floor(c.min())), int(np.floor(r.min()))
    win = Window(c0, r0, int(np.floor(c.max())) - c0 + 2, int(np.floor(r.max())) - r0 + 2)
    grid = ds.read(1, window=win, boundless=True, fill_value=np.nan).astype(float)
    if ds.nodata is not None:
        grid[grid == ds.nodata] = np.nan
    fc, fr = c - c0, r - r0
    ic, ir = np.floor(fc).astype(int), np.floor(fr).astype(int)
    dc, dr = fc - ic, fr - ir
    bilinear = (
        grid[ir, ic] * (1 - dc) * (1 - dr)
        + grid[ir, ic + 1] * dc * (1 - dr)
        + grid[ir + 1, ic] * (1 - dc) * dr
        + grid[ir + 1, ic + 1] * dc * dr
    )
    # Au bord du raster (ou d'une tuile), un voisin manque : on prend le pixel le plus proche plutôt que rien.
    nearest = grid[np.rint(fr).astype(int), np.rint(fc).astype(int)]
    return np.where(np.isnan(bilinear), nearest, bilinear)


class LocalDemElevation:
    """MNT local : tous les GeoTIFF d'un dossier (variable RANDOFORGE_DEM_DIR), dans n'importe quelle projection.

    Pour l'auto-hébergement ou une source plus précise (swissALTI3D, MNT régional…) :
    prioritaire sur les autres fournisseurs, les points hors emprise passent au suivant.
    """

    def __init__(self, directory: Path, name: str | None = None):
        self.files = sorted(p for p in Path(directory).glob("**/*") if p.suffix.lower() in {".tif", ".tiff"})
        self.name = name or f"MNT local ({Path(directory).name})"

    def elevations(self, points: list[LatLon]) -> list[float | None]:
        load_rasterio()
        import rasterio
        from rasterio.warp import transform_bounds

        out: list[float | None] = [None] * len(points)
        for f in self.files:
            remaining = [i for i, v in enumerate(out) if v is None]
            if not remaining:
                break
            with rasterio.open(f) as ds:
                w, s, e, n = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds) if ds.crs else ds.bounds
                inside = [i for i in remaining if s <= points[i][0] <= n and w <= points[i][1] <= e]
                if not inside:
                    continue
                z = sample_bilinear(ds, [points[i] for i in inside])
            for i, v in zip(inside, z, strict=True):
                if not np.isnan(v):
                    out[i] = round(float(v), 2)
        return out


@dataclass
class ElevationResult:
    values: list[float | None]
    sources: list[str | None]
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        counts: dict[str, int] = defaultdict(int)
        for s in self.sources:
            counts[s or "aucune"] += 1
        n = len(self.sources)
        return ", ".join(f"{k} {round(100 * v / n)} %" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))


class ElevationChain:
    """Interroge les fournisseurs dans l'ordre ; chaque point prend la première valeur disponible."""

    def __init__(self, providers: list):
        self.providers = providers

    def elevations(self, points: list[LatLon]) -> ElevationResult:
        values: list[float | None] = [None] * len(points)
        sources: list[str | None] = [None] * len(points)
        remaining = list(range(len(points)))
        errors: list[str] = []
        for provider in self.providers:
            if not remaining:
                break
            try:
                got = provider.elevations([points[i] for i in remaining])
            except (HttpError, ValueError, OSError) as exc:  # panne d'une source : on passe à la suivante
                errors.append(f"{provider.name} : {exc}")
                continue
            for i, v in zip(remaining, got, strict=True):
                if v is not None:
                    values[i], sources[i] = v, provider.name
            remaining = [i for i in remaining if values[i] is None]
        if remaining and errors and len(remaining) == len(points):
            raise ValueError("Altimétrie indisponible : " + " ; ".join(errors))
        return ElevationResult(values, sources, errors)
