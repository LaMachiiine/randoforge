"""Faune observée : groupes, espèces à connaître, noms français."""

import pytest
from mcp import Client

from randoforge.core import wildlife

from .test_server import LANS, MOUCHEROTTE, call


def test_notable_species_and_month_window():
    assert wildlife.notable("Vipera aspis") == "vipère, venimeuse" and wildlife.notable("Canis lupus")
    assert wildlife.notable("Vipera") and not wildlife.notable("Viperaceae sp")
    assert wildlife.month_window(7) == (6, 8) and wildlife.month_window(12) == (11, 12)


@pytest.mark.anyio
async def test_wildlife_tool(server):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        rep = await call(client, "wildlife", {"route_id": rid, "date": "2026-07-15"})
        assert rep["groupes"]["mammifères"] == ["Chamois (Rupicapra rupicapra) : 30 obs."]
        assert rep["a_connaitre"][0].startswith("Vipère aspic (Vipera aspis) : 2 obs.")
        assert rep["periode"] == "juin–août 2016–2026" and "GBIF" in rep["source"]
