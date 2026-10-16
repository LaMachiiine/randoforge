"""Transports en commun : regroupement des passages, retour après l'arrivée estimée."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from mcp import Client

from randoforge.core import transit

from .conftest import stop_time
from .test_server import LANS, MOUCHEROTTE, call

TZ = ZoneInfo("Europe/Paris")


def test_group_filters_carpooling_terminus_and_duplicates():
    times = [stop_time(t) for t in ("07:10", "07:11", "17:00")] + [
        stop_time("12:00", agency="Mobilités M - Covoit Lignes +"),
        stop_time("13:00", stop="Terminus", terminus="Terminus"),
        stop_time("09:00", day="2026-10-20"),  # autre jour
    ]
    after = datetime(2026, 10, 19, 16, 0, tzinfo=TZ)
    out = transit.group(times, 45.1279, 5.5885, TZ, date(2026, 10, 19), after)
    assert [(li.ligne, li.horaires) for li in out.lignes] == [("T64", ["07:10", "17:00"])]
    assert out.premier_apres == ("17:00", "T64", "Grenoble") and out.arrets[0][0] == "Mairie"


@pytest.mark.anyio
async def test_public_transport_tool(server):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE, LANS]}))["route_id"]
        rep = await call(client, "public_transport", {"route_id": rid, "date": "2026-10-19", "start_time": "08:30"})
        assert rep["depart"]["lignes"][0]["horaires"] == ["07:10", "17:00", "18:04"]
        # Tracé de la doublure : aller simple (départ et arrivée distincts) → retour cherché à l'arrivée.
        assert rep["arrivee"]["premier_retour"].startswith("17:00") and "Transitous" in rep["source"]


@pytest.mark.anyio
async def test_water_and_huts_reports_state_and_recent_comments(server):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        rep = await call(client, "water_and_huts", {"route_id": rid})
        by_name = {p["nom"]: p for p in rep["points"]}
        assert by_name["Source"]["etat"] == "Débit intermittent"
        assert by_name["Source"]["derniers_avis"] == ["12/08/2026 : La source coule à flot. (Randonneur)"]
        assert by_name["Cabane fermée"]["equipement"] == "6 places, poêle"
        assert "1 tari" in rep["message"] and "Refuges.info" in rep["source"]


def test_dry_or_destroyed_points_are_never_used_for_the_night():
    from randoforge.core.bivouac import is_closed, unusable

    assert unusable({"etat": "Tari définitivement"}) and unusable({"etat": "Détruite"})
    assert not unusable({"etat": "Débit intermittent"}) and is_closed({"etat": "Fermée"})


def test_tile_position_of_a_point():
    from randoforge.engines.coverage import tile_of

    x, y, px, py = tile_of(45.188, 5.724)
    assert (x, y) == (2113, 1470) and 0 <= px < 4096 and 0 <= py < 4096


@pytest.mark.anyio
async def test_mobile_coverage_tool(server):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        rep = await call(client, "mobile_coverage", {"route_id": rid})
        assert 0 < rep["reseau_pct"] < 100 and rep["reseau_pct"] == rep["voix_pct"] == rep["par_operateur"]["SFR"]
        assert rep["par_operateur"]["Orange"] == 0 and rep["zones_sans_reseau"] and "Arcep" in rep["source"]
