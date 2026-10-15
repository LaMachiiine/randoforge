from pathlib import Path

import pytest
from mcp import Client

from randoforge.core.models import Route, TrackPoint
from randoforge.formats.gpx import read_gpx, write_gpx
from randoforge.server import build_server
from randoforge.storage import RouteStore

FIXTURE = Path(__file__).parent / "fixtures" / "boucle_synthetique.gpx"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def store(tmp_path):
    return RouteStore(tmp_path)


def test_gpx_roundtrip():
    route = Route(
        route_id="r_2026-10-15_abcdef",
        name="Test",
        source="test",
        points=[TrackPoint(lat=45.0, lon=6.0, ele=1000.0), TrackPoint(lat=45.001, lon=6.001, ele=1010.5)],
    )
    name, points = read_gpx(write_gpx(route))
    assert name == "Test"
    assert points == route.points


def test_store_rejects_path_traversal(store):
    with pytest.raises(ValueError):
        store.dir_for("../../etc")


@pytest.mark.anyio
async def test_tools_end_to_end(store):
    async with Client(build_server(store)) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert {"import_gpx", "compute_stats", "get_route", "list_routes", "export_route"} <= tools

        res = await client.call_tool("import_gpx", {"path": str(FIXTURE)})
        assert not res.is_error, res.content
        summary = res.structured_content
        assert summary["name"] == "Boucle synthétique"
        assert summary["stats"]["is_loop"] is True
        assert summary["stats"]["d_plus_m"] == summary["stats"]["d_minus_m"] == 400
        route_id = summary["route_id"]

        # Un marcheur plus rapide doit obtenir une durée plus courte.
        res = await client.call_tool("compute_stats", {"route_id": route_id, "up_m_per_h": 500})
        assert res.structured_content["stats"]["duration_min"] < summary["stats"]["duration_min"]

        res = await client.call_tool("export_route", {"route_id": route_id})
        files = res.structured_content["files"]
        assert Path(files["gpx"]).exists()
        fiche = Path(files["md"]).read_text(encoding="utf-8")
        assert "d_plus: 400" in fiche

        res = await client.call_tool("list_routes", {})
        assert [r["route_id"] for r in res.structured_content["routes"]] == [route_id]


@pytest.mark.anyio
async def test_unknown_route_is_a_clear_error(store):
    async with Client(build_server(store)) as client:
        res = await client.call_tool("get_route", {"route_id": "r_2026-01-01_000000"})
        assert res.is_error
        assert "Itinéraire inconnu" in res.content[0].text
