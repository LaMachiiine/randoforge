from pathlib import Path

import gpxpy
import pytest
from mcp import Client

from randoforge.core.models import Route, TrackPoint
from randoforge.formats.gpx import read_gpx, write_gpx

FIXTURE = Path(__file__).parent / "fixtures" / "boucle_synthetique.gpx"
LANS = {"lat": 45.1279, "lon": 5.5885}
MOUCHEROTTE = {"lat": 45.1503, "lon": 5.6303}


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


async def call(client, tool, args):
    res = await client.call_tool(tool, args)
    assert not res.is_error, res.content[0].text
    return res.structured_content


@pytest.mark.anyio
async def test_import_gpx_with_file_elevation(server):
    async with Client(server) as client:
        summary = await call(client, "import_gpx", {"path": str(FIXTURE), "elevation": "file"})
        assert summary["name"] == "Boucle synthétique"
        assert summary["stats"]["is_loop"] is True
        assert summary["stats"]["d_plus_m"] == summary["stats"]["d_minus_m"] == 400

        faster = await call(client, "compute_stats", {"route_id": summary["route_id"], "up_m_per_h": 500})
        assert faster["stats"]["duration_min"] < summary["stats"]["duration_min"]


@pytest.mark.anyio
async def test_import_gpx_with_dem_replaces_elevations(server):
    async with Client(server) as client:
        summary = await call(client, "import_gpx", {"path": str(FIXTURE)})
        assert summary["stats"]["elevation_source"] == "Relief de test 100 %"
        assert summary["stats"]["d_plus_m"] != 400


@pytest.mark.anyio
async def test_full_workflow(server, services):
    async with Client(server) as client:
        places = await call(client, "geocode", {"query": "Lans-en-Vercors"})
        assert places["places"][0]["lat"] == pytest.approx(45.1279)

        route = await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE], "name": "Moucherotte"})
        stats = route["stats"]
        assert stats["distance_km"] == pytest.approx(7.585, rel=0.01)  # = track-length BRouter
        assert stats["d_plus_m"] > 0 and stats["elevation_source"] == "Relief de test 100 %"
        assert services.router.calls == [([(45.1279, 5.5885), (45.1503, 5.6303)], "hiking-mountain")]
        rid = route["route_id"]

        annotated = await call(client, "annotate_route", {"route_id": rid})
        names = {p["nom"] for p in annotated["pois"]}
        assert {"Le Furon", "Source de Moucherotte"} <= names
        assert "Lans Mairie" not in names  # abribus exclu
        assert any(p["via"] == "gué" for p in annotated["pois"])
        assert annotated["warnings"]
        kms = [p["km"] for p in annotated["pois"]]
        assert kms == sorted(kms)

        report = await call(client, "validate_route", {"route_id": rid})
        ids = {c["id"] for c in report["checks"]}
        assert report["status"] == "error"
        assert "G6" in ids  # le point du Moucherotte est à ~270 m du chemin : vraie erreur détectée
        assert "D7" in ids  # gué
        assert all(c["id"] != "A4" for c in report["checks"])  # traversées de route ignorées

        files = (await call(client, "export_route", {"route_id": rid}))["files"]
        gpx = gpxpy.parse(Path(files["gpx"]).read_text(encoding="utf-8"))
        assert any("gué" in (w.name or "") for w in gpx.waypoints)
        fiche = Path(files["md"]).read_text(encoding="utf-8")
        assert "## À voir en chemin" in fiche and "validation: error" in fiche


@pytest.mark.anyio
async def test_loop_closes_on_start(server, services):
    async with Client(server) as client:
        await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE], "loop": True})
        waypoints, _ = services.router.calls[0]
        assert waypoints[0] == waypoints[-1]


@pytest.mark.anyio
async def test_find_pois_sorted_by_interest(server):
    async with Client(server) as client:
        res = await call(client, "find_pois", {**LANS, "radius_km": 5, "limit": 5})
        scores = [p["poi"]["score"] for p in res["pois"]]
        assert scores == sorted(scores, reverse=True)
        assert len(scores) == 5 and res["truncated"]


@pytest.mark.anyio
async def test_invalid_inputs_are_rejected(server):
    async with Client(server) as client:
        res = await client.call_tool("route_between", {"waypoints": [LANS]})
        assert res.is_error  # au moins 2 points
        res = await client.call_tool("get_route", {"route_id": "r_2026-01-01_000000"})
        assert res.is_error and "Itinéraire inconnu" in res.content[0].text
