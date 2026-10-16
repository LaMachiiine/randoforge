"""Précision sur des références officielles (réseau requis) : itinéraires publiés par les parcs
nationaux des Écrins et des Cévennes (Geotrek), altitudes officielles des sommets.

Seuils fixés d'après la calibration (docs/10 - Architecture/Calibration du dénivelé.md) avec une marge :
écart médian mesuré 4,2 % (Écrins) et 6,0 % (Cévennes) sur 40 itinéraires par parc.
"""

from __future__ import annotations

import statistics
import tempfile
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from randoforge.app import App
from randoforge.core.models import Route, TrackPoint
from randoforge.core.stats import compute_stats
from randoforge.engines.geotrek import GeotrekReference
from randoforge.http import CachedHttp, HttpError
from randoforge.services import Services
from randoforge.storage import RouteStore

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    return App(RouteStore(Path(tempfile.mkdtemp())), Services.from_env(home)), CachedHttp(home / "cache.sqlite")


@pytest.mark.parametrize("park", ["ecrins", "cevennes"])
def test_d_plus_matches_official_treks(app, park):
    application, http = app
    try:
        treks = GeotrekReference(http).treks(park, 12)
    except HttpError as exc:
        pytest.skip(f"Geotrek {park} indisponible : {exc}")
    assert len(treks) >= 10
    d_errors, dist_errors = [], []
    for t in treks:
        route = Route(route_id="r_2000-01-01_000000", name=t.name, source="geotrek",
                      points=[TrackPoint(lat=la, lon=lo) for la, lo, _ in t.coords])  # fmt: skip
        application.apply_dem(route)
        stats, _ = compute_stats(route.points)
        d_errors.append(100 * (stats.d_plus_m - t.ascent_m) / t.ascent_m)
        dist_errors.append(100 * (stats.distance_km - t.length_km) / t.length_km)
    assert statistics.median(abs(e) for e in d_errors) <= 8.0
    assert abs(statistics.median(d_errors)) <= 8.0
    assert statistics.median(abs(e) for e in dist_errors) <= 1.0


def test_rounded_summits_match_official_altitudes(app):
    """Sommets arrondis (Cévennes) : le MNT IGN doit coller à l'altitude officielle."""
    application, _ = app
    try:
        els = application.overpass(
            '[out:json][timeout:60];node["natural"="peak"]["ele"]["name"](44.15,3.5,44.45,3.9);out 30;'
        )
    except ToolError as exc:  # service public saturé : on teste RandoForge, pas la disponibilité d'Overpass
        pytest.skip(f"Overpass indisponible : {exc}")
    pts, official = [], []
    for el in els:
        try:
            official.append(float(el["tags"]["ele"].replace(",", ".")))
            pts.append((el["lat"], el["lon"]))
        except ValueError:
            continue
    dem = application.elevations(pts).values
    errors = [d - o for d, o in zip(dem, official, strict=True) if d is not None]
    assert len(errors) >= 15
    assert statistics.median(abs(e) for e in errors) <= 5.0
