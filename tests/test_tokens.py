"""Économie de jetons : réponses compactes, listes plafonnées, rappels factorisés."""

import json

import pytest
from mcp import Client

from randoforge.core.models import Check, Poi

from .test_server import LANS, MOUCHEROTTE, call


def test_compact_models_drop_empty_optional_fields_only():
    poi = Poi(km=0.0, categorie="eau", type="spring", lat=45, lon=6, distance_m=0, detour_m=0, score=0.4, osm_id="n/1")
    data = poi.model_dump()
    assert "nom" not in data and "via" not in data and "intermittent" not in data
    assert data["km"] == 0.0 and data["detour_m"] == 0  # les zéros sont des informations
    assert Check(id="X", level="info", message="m").model_dump() == {"id": "X", "level": "info", "message": "m"}


@pytest.mark.anyio
async def test_tool_text_is_compact_json_equal_to_structured(server):
    async with Client(server) as client:
        res = await client.call_tool("route_between", {"waypoints": [LANS, MOUCHEROTTE]})
        text = res.content[0].text
        assert "\n" not in text and ": " not in text  # pas d'indentation ni d'espaces superflus
        assert json.loads(text) == res.structured_content
        assert "params" not in res.structured_content["stats"]  # paramètres de calcul hors résumé


@pytest.mark.anyio
async def test_lists_are_capped_and_common_warnings_factorised(server):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        ann = await call(client, "annotate_route", {"route_id": rid, "limit": 3})
        assert len(ann["pois"]) == 3 and ann["total"] > 3
        assert any(p.get("via") == "gué" for p in ann["pois"])  # les gués restent toujours visibles
        assert [p["km"] for p in ann["pois"]] == sorted(p["km"] for p in ann["pois"])

        spots = await call(client, "find_bivouac_spots", {"route_id": rid, "limit": 5})
        assert len(spots["emplacements"]) <= 5 and spots["total"] >= len(spots["emplacements"])
        repeated = [w for s in spots["emplacements"] for w in s.get("avertissements", []) if w in spots["rappels"]]
        assert repeated == []


@pytest.mark.anyio
async def test_geocode_near_is_forwarded(server, services):
    calls = []
    services.nominatim.geocode = lambda q, limit, country, near=None: calls.append(near) or []
    async with Client(server) as client:
        await call(client, "geocode", {"query": "Moucherotte", "near": LANS})
    assert calls == [(LANS["lat"], LANS["lon"])]


@pytest.mark.anyio
async def test_analyze_route_does_everything_in_one_call(server):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        res = await call(client, "analyze_route", {"route_id": rid, "limit_pois": 5})
        assert res["validation"]["status"] in {"ok", "warning", "error"}
        assert len(res["pois"]) <= 5 and res["pois_total"] >= len(res["pois"])
        assert "passages_techniques" in res and res["zones"]  # parc national des doublures
        ids = {c["id"] for c in res["validation"]["checks"]}
        assert "D7" in ids  # le gué a bien été analysé avant la validation


@pytest.mark.anyio
async def test_weather_forecast_validates_the_route_itself(server, soon):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        w = await call(client, "weather_forecast", {"route_id": rid, "date": soon.isoformat()})
        assert w["validation_status"] in {"ok", "warning", "error"}
        assert any(a.startswith("G6") for a in w["alertes_itineraire"])  # point non atteint détecté sans validate_route
        assert (await call(client, "get_route", {"route_id": rid})).get("prochaine_etape") is None


@pytest.mark.anyio
async def test_find_and_import_official_trek(server):
    async with Client(server) as client:
        found = await call(client, "find_official_treks", {"query": "Moucherotte", **LANS})
        trek = found["treks"][0]
        assert trek["nom"] == "Montée au Moucherotte" and trek["parc"] == "ecrins"
        route = await call(client, "import_official_trek", {"parc": trek["parc"], "trek_id": trek["trek_id"]})
        assert route["source"] == "officiel:ecrins:1"
        assert route["stats"]["distance_km"] == pytest.approx(7.585, rel=0.02)
        res = await client.call_tool("find_official_treks", {})
        assert res.is_error  # ni nom ni lieu
