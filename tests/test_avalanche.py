"""Terrain avalancheux calculé sur le relief : pente traversée, pente au-dessus, tronçons."""

import math

import numpy as np
import pytest
from mcp import Client

from randoforge.core import avalanche as aval

from .test_server import LANS, MOUCHEROTTE, call

D = 1 / 3600  # maille d'une seconde d'arc (~31 m en latitude)


def _grid(z):
    return aval.Grid(z=z.astype(float), top=45.1, left=6.0, dlat=D, dlon=D)


def _rows(n):
    return 45.1 - (np.arange(n) + 0.5) * D


def test_slope_of_a_known_plane():
    rise = math.tan(math.radians(35)) * D * 111_320  # 35° vers le nord
    z = np.tile((np.arange(200)[::-1] * rise)[:, None], (1, 200))
    assert aval.slope_deg(_grid(z))[50:150, 50:150].mean() == pytest.approx(35, abs=0.5)


def test_path_on_and_under_steep_slopes():
    n = 200
    rise35 = math.tan(math.radians(35)) * D * 111_320
    # Moitié sud plate, moitié nord : versant de 35° qui monte vers le nord.
    z = np.where(np.arange(n)[:, None] < 100, (100 - np.arange(n)[:, None]) * rise35, 0.0) * np.ones((1, n))
    g = _grid(z)
    lons = np.full(3, 6.0 + 100 * D)
    on_slope = _rows(n)[[50]]  # sur le versant
    below = _rows(n)[[105]]  # au pied, ~150 m sous la pente
    far = _rows(n)[[190]]  # 2,8 km plus loin : hors de portée
    under, reach, height = aval.exposure(g, np.concatenate([on_slope, below, far]), lons, np.full(3, np.nan))
    assert under[0] >= 34 and under[2] < 5  # pente traversée / plat
    assert reach[1] >= 34 and height[1] > 50  # au pied : dominé par le versant
    assert reach[2] == 0  # trop loin, angle de portée < 22°


def test_sections_are_merged_when_close():
    cum = np.arange(0, 2000, 50.0)
    under = np.zeros(len(cum))
    reach = np.zeros(len(cum))
    under[10:14] = 38  # km 0,5–0,7 traversé
    reach[15:20] = 45  # km 0,75–1,0 dessous : à moins de 100 m, même tronçon
    under[30:31] = 31  # 50 m isolés : ignorés
    out = aval.sections(cum, under, reach, np.full(len(cum), 120.0))
    assert len(out) == 1 and out[0].cross_deg == 38 and out[0].above_deg == 45


@pytest.mark.anyio
async def test_avalanche_tool_on_gentle_terrain(server):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        rep = await call(client, "avalanche_terrain", {"route_id": rid})
        assert rep["part_exposee_pct"] == 0 and "Aucune pente" in rep["message"]
