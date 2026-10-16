"""Dossier de sortie : analyses retenues selon la sortie, trace GPX et page unique."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from mcp import Client

from .test_server import LANS, MOUCHEROTTE, call


@pytest.mark.anyio
async def test_day_hike_dossier_has_weather_wildlife_coverage_and_one_page(server, soon):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE, LANS]}))["route_id"]
        rep = await call(client, "prepare_dossier", {"route_id": rid, "date": soon.isoformat()})
        assert {"météo", "faune", "réseau mobile"} <= set(rep["sections"])
        assert "transports" not in rep["sections"] and "transports" not in rep.get("non_inclus", {})
        assert "eau et refuges" in rep["non_inclus"]  # sortie à la journée
        assert rep["validation_status"] in {"ok", "warning", "error"}
        page = Path(rep["files"]["dossier"]).read_text(encoding="utf-8")
        assert "leaflet" in page and "Faune" in page and Path(rep["files"]["gpx"]).is_file()
        # Les analyses sont enregistrées : la fiche suivante n'a pas à les relancer.
        assert (await call(client, "get_route", {"route_id": rid}))["validation_status"] == rep["validation_status"]


@pytest.mark.anyio
async def test_transport_only_on_request_and_weather_out_of_range(server):
    later = (date.today() + timedelta(days=40)).isoformat()
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        rep = await call(client, "prepare_dossier", {"route_id": rid, "date": later, "transport": True})
        assert "transports" in rep["sections"]
        assert "météo" not in rep["sections"] and "prévision" in rep["non_inclus"]["météo"]


@pytest.mark.anyio
async def test_long_calls_report_progress_and_hide_the_context(server, soon):
    seen: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress, total, message):
        seen.append((progress, total, message))

    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert "ctx" not in tools["prepare_dossier"].input_schema["properties"]
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE, LANS]}))["route_id"]
        res = await client.call_tool("prepare_dossier", {"route_id": rid, "date": soon.isoformat()},
                                     progress_callback=on_progress)  # fmt: skip
        assert not res.is_error
        assert seen and seen[-1][2] == "écriture de la trace et du dossier"
        assert [p for p, _, _ in seen] == sorted(p for p, _, _ in seen) and all(p <= t for p, t, _ in seen)
        seen.clear()
        await client.call_tool("generate_loop_candidates", {"start": LANS, "distance_km": 8, "n": 1, "directions": 3},
                               progress_callback=on_progress)  # fmt: skip
        assert any("direction" in (m or "") for _, _, m in seen)
