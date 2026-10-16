"""Enneigement : saison, limite de la neige, facteurs de durée, décodage satellite, outil complet."""

from datetime import date, timedelta

import numpy as np
import pytest
from mcp import Client

from randoforge.core import snow
from randoforge.core.models import TrackPoint, WalkerProfile

from .test_server import LANS, MOUCHEROTTE, call


def test_season_and_altitude_gate():
    assert snow.in_season(date(2026, 2, 10), 45.6, 1600)
    assert not snow.in_season(date(2026, 2, 10), 45.6, 400)  # trop bas
    assert not snow.in_season(date(2026, 8, 10), 45.6, 1600)  # été, moyenne montagne
    assert snow.in_season(date(2026, 8, 10), 45.9, 3200)  # été, haute montagne
    assert snow.in_season(date(2026, 8, 10), -41.0, 1600)  # hiver austral


def test_snow_line_from_pixels():
    elev = np.repeat(np.arange(800, 2000, 25), 4).astype(float)
    values = np.where(elev >= 1300, 80, 0).astype(np.int16)
    values[::7] = -1  # quelques nuages, ignorés
    line, lo, hi = snow.snow_line(elev, values)
    assert line == 1300 and lo == 800
    assert snow.snow_line(elev, np.zeros_like(values))[0] is None  # aucune neige vue
    assert snow.snow_line(elev, np.full_like(values, -1))[0] is None  # tout sous les nuages


def test_slowdown_factors():
    assert snow.factor(5, False, False) == 1.25  # peu épaisse
    assert snow.factor(15, True, False) == 1.5 and snow.factor(15, True, True) == 1.4
    assert snow.factor(30, True, False) == 2.0
    assert snow.factor(60, True, False) == 3.0 and snow.factor(60, True, True) == 2.2
    assert snow.factor(60, False, False) == 1.5  # neige ancienne épaisse


def test_duration_only_slowed_on_snowy_sections():
    pts = [TrackPoint(lat=45 + i * 1e-4, lon=6.0, ele=1000 + i) for i in range(1000)]  # ~11 km, 1000 → 2000 m
    cum = np.arange(1000) * 11.1
    states = [(i, snow.PointSnow(seen=None, seen_day=None, depth_cm=15, fresh=True)) for i in range(0, 1000, 25)]
    normal, total, km, sections = snow.duration_with_snow(pts, cum, states, 1500, WalkerProfile(), False)
    assert 0.45 < km / (cum[-1] / 1000) < 0.55  # au-dessus de la limite (1 500 m) seulement
    assert normal < total < normal * 1.5 and sections[0][2] == 1.5


def test_gibs_palette_is_decoded_by_colour():
    from rasterio.io import MemoryFile

    from randoforge.engines.snow import CLOUD, UNKNOWN, _decode

    data = np.array([[0, 55, 105, 200]], dtype=np.uint8)
    palette = {i: (0, 0, 0, 0) for i in range(256)}
    palette[55] = (250, 120, 60, 255)  # neige NDSI 55
    palette[105] = (0, 191, 255, 0)  # nuage (couleur de la palette GIBS, index variable selon le satellite)
    palette[200] = (189, 0, 189, 0)  # nuit
    with MemoryFile() as mem:
        with mem.open(driver="PNG", width=4, height=1, count=1, dtype="uint8") as ds:
            ds.write(data, 1)
            ds.write_colormap(1, palette)
        decoded = _decode(mem.read())
    assert decoded.tolist() == [[0, 55, CLOUD, UNKNOWN]]


@pytest.mark.anyio
async def test_snow_conditions_tool(server):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        rep = await call(client, "snow_conditions", {"route_id": rid, "date": date.today().isoformat()})
        assert rep["applicable"] and 1100 <= rep["limite_neige_m"] <= 1300  # neige des doublures au-dessus de 1 200 m
        assert 0 < rep["part_enneigee_pct"] < 100 and rep["duree_neige"] != rep["duree_normale"]
        assert rep["epaisseur_modele_cm"] == [15, 15] and rep["troncons_enneiges"]
        summer = await call(client, "snow_conditions", {"route_id": rid, "date": "2026-08-01"})
        assert summer["applicable"] is False  # été, sous 2 000 m
        later = (date.today() + timedelta(days=30)).isoformat()
        far = await call(client, "snow_conditions", {"route_id": rid, "date": later, "force": True})
        assert far["applicable"] and "Sortie dans 30 j" in " ".join(far.get("avertissements", []))
