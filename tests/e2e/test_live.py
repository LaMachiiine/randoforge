"""Tests de bout en bout sur les vrais services (réseau requis, plusieurs minutes).

    uv run pytest -m e2e

Le serveur est lancé en sous-processus stdio, exactement comme par Claude Code. Si un service
public est indisponible (Overpass saturé…), le test est sauté plutôt qu'échoué : ces tests
vérifient RandoForge, pas la disponibilité des serveurs gratuits.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import gpxpy
import pytest
from mcp import Client, StdioServerParameters

pytestmark = [pytest.mark.e2e, pytest.mark.anyio]
ROOT = Path(__file__).resolve().parents[2]
UNAVAILABLE = ("indisponible", "injoignable", "timed out")


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    # RANDOFORGE_E2E_HOME permet de réutiliser un cache entre deux lancements (plus rapide).
    return Path(os.environ.get("RANDOFORGE_E2E_HOME") or tmp_path_factory.mktemp("randoforge-home"))


@asynccontextmanager
async def server(home: Path):
    params = StdioServerParameters(
        command="uv",
        args=["run", "--directory", str(ROOT), "randoforge"],
        env={**os.environ, "RANDOFORGE_HOME": str(home)},
    )
    try:
        async with Client(params, read_timeout_seconds=600) as client:
            yield client
    except BaseExceptionGroup as group:
        # Le client MCP enveloppe tout dans des groupes d'exceptions : on fait remonter la vraie cause
        # (saut ou échec du test) pour que pytest affiche son message.
        inner: BaseException = group
        while isinstance(inner, BaseExceptionGroup) and len(inner.exceptions) == 1:
            inner = inner.exceptions[0]
        raise inner from None


async def call(client, tool: str, args: dict) -> dict:
    res = await client.call_tool(tool, args)
    if res.is_error:
        text = res.content[0].text
        if any(k in text for k in UNAVAILABLE):
            pytest.skip(f"service externe indisponible pendant {tool} : {text[:200]}")
        pytest.fail(f"{tool} : {text}")
    return res.structured_content


async def test_day_loop_from_autrans(home):
    """Boucle à la journée générée automatiquement, analysée, validée et exportée."""
    async with server(home) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        assert len(tools) == 35

        place = (await call(c, "geocode", {"query": "Autrans", "country": "fr", "limit": 1}))["places"][0]
        assert 45.1 < place["lat"] < 45.25

        loops = await call(c, "generate_loop_candidates", {"start": {"lat": place["lat"], "lon": place["lon"]},
                                                           "distance_km": 10, "d_plus_m": 400, "n": 2})  # fmt: skip
        best = loops["candidates"][0]["route"]
        s = best["stats"]
        assert abs(s["distance_km"] - 10) / 10 < 0.2
        assert s["is_loop"] and s["d_plus_m"] == pytest.approx(s["d_minus_m"], rel=0.02)
        assert s["elevation_source"].startswith("IGN")
        rid = best["route_id"]

        tomorrow = date.today() + timedelta(days=1)
        await call(c, "set_constraints", {"route_id": rid, "date": tomorrow.isoformat(), "start_time": "09:00"})
        pois = await call(c, "annotate_route", {"route_id": rid})
        assert all(a["km"] <= b["km"] for a, b in zip(pois["pois"], pois["pois"][1:], strict=False))
        await call(c, "technical_passages", {"route_id": rid})
        quality = await call(c, "data_quality", {"route_id": rid})
        assert quality["qualite"]["sur_chemin_pct"] >= 95  # un tracé BRouter suit des chemins
        weather = await call(c, "weather_forecast", {"route_id": rid})
        assert weather["points"] and weather["date"] == tomorrow.isoformat()

        report = await call(c, "validate_route", {"route_id": rid})
        assert report["status"] in {"ok", "warning", "error"}
        assert any(ch["id"] == "D4" for ch in report["checks"])  # horaires vérifiés

        files = (await call(c, "export_route", {"route_id": rid, "formats": ["gpx", "md", "html", "roadbook"]}))[
            "files"
        ]
        gpx = gpxpy.parse(Path(files["gpx"]).read_text(encoding="utf-8"))
        assert len(gpx.tracks[0].segments[0].points) > 100
        assert "leaflet" in Path(files["html"]).read_text(encoding="utf-8")


async def test_multi_day_trek_hauts_plateaux(home):
    """Itinérance : réserve naturelle, bivouacs/refuges, découpage en étapes, un GPX par jour."""
    async with server(home) as c:
        wps = []
        for q in ("Corrençon-en-Vercors", "Cabane de Pré Peyret", "Gresse-en-Vercors"):
            p = (await call(c, "geocode", {"query": q, "country": "fr", "limit": 1}))["places"][0]
            wps.append({"lat": p["lat"], "lon": p["lon"]})
        route = await call(c, "route_between", {"waypoints": wps, "name": "Traversée des Hauts-Plateaux"})
        rid = route["route_id"]
        assert route["stats"]["distance_km"] > 30

        await call(c, "set_constraints", {"route_id": rid, "with_dog": True, "max_duration_h": 7})
        zones = await call(c, "route_areas", {"route_id": rid})
        assert any("réserve" in z["kind"] and z["chiens"] == "interdits" for z in zones["zones"])

        spots = await call(c, "find_bivouac_spots", {"route_id": rid, "limit": 100})
        if any("refuges.info" in r for r in spots["rappels"]):
            pytest.skip(f"refuges.info indisponible : {spots['rappels']}")
        assert any(s["source"] == "refuges.info" for s in spots["emplacements"])

        plan = await call(c, "plan_stages", {"route_id": rid})
        assert len(plan["etapes"]) >= 3
        assert all(st["duree_min"] <= 7 * 60 for st in plan["etapes"])

        report = await call(c, "validate_route", {"route_id": rid})
        assert any(ch["id"] == "C1" and ch["level"] == "error" for ch in report["checks"])  # chien en réserve

        files = (await call(c, "export_route", {"route_id": rid}))["files"]
        day_files = [k for k in files if k.startswith("gpx_jour_")]
        assert len(day_files) == len(plan["etapes"])
        full = gpxpy.parse(Path(files["gpx"]).read_text(encoding="utf-8"))
        assert len(full.tracks) == 1  # GPX complet en une seule trace

        dossier = await call(c, "prepare_dossier", {"route_id": rid})
        assert "eau et refuges" in dossier["sections"]  # itinérance : eau et cabanes d'office
        assert len([k for k in dossier["files"] if k.startswith("gpx_jour_")]) == len(plan["etapes"])


async def test_abroad_uses_copernicus(home):
    """Hors de France, l'altitude vient de Copernicus et l'utilisateur en est averti."""
    async with server(home) as c:
        route = await call(c, "route_between", {"waypoints": [{"lat": 46.0207, "lon": 7.7491},
                                                              {"lat": 46.0040, "lon": 7.7390}]})  # fmt: skip
        assert "Copernicus" in route["stats"]["elevation_source"]
        assert any("Copernicus" in w for w in route["warnings"])


async def test_roundtrip_import_and_reference(home, tmp_path):
    """Un GPX exporté, réimporté, doit suivre les chemins et coïncider avec l'original."""
    async with server(home) as c:
        route = await call(c, "route_between", {"waypoints": [{"lat": 45.1279, "lon": 5.5885},
                                                              {"lat": 45.1420, "lon": 5.6100}]})  # fmt: skip
        gpx_path = (await call(c, "export_route", {"route_id": route["route_id"], "formats": ["gpx"]}))["files"]["gpx"]
        imported = await call(c, "import_gpx", {"path": gpx_path, "name": "Réimport"})
        assert imported["stats"]["distance_km"] == pytest.approx(route["stats"]["distance_km"], rel=0.01)
        assert imported["stats"]["d_plus_m"] == pytest.approx(route["stats"]["d_plus_m"], abs=5)

        quality = await call(c, "data_quality", {"route_id": imported["route_id"]})
        assert quality["qualite"]["sur_chemin_pct"] >= 95
        ref = await call(
            c, "compare_with_reference", {"route_id": imported["route_id"], "reference_id": route["route_id"]}
        )
        assert ref["comparaison"]["ecart_max_m"] < 5


async def test_snow_on_pierre_sur_haute(home):
    """Enneigement réel : satellites et modèle, un jour d'hiver puis aujourd'hui, au même tracé."""
    async with server(home) as c:
        # Col du Béal → Pierre-sur-Haute (Monts du Forez, 1 634 m).
        route = await call(c, "route_between", {"waypoints": [{"lat": 45.6869, "lon": 3.7826},
                                                              {"lat": 45.6560, "lon": 3.8062}]})  # fmt: skip
        winter = await call(c, "snow_conditions", {"route_id": route["route_id"], "date": "2026-02-15"})
        assert winter["applicable"] and winter["part_enneigee_pct"] > 50  # neige au-dessus de ~1 300 m ce jour-là
        assert winter["duree_neige"] != winter["duree_normale"]
        assert any("GIBS" in s for s in winter["sources"])
        now = await call(c, "snow_conditions", {"route_id": route["route_id"], "date": date.today().isoformat(),
                                                "force": True})  # fmt: skip
        assert now["applicable"] and now.get("vu_par_satellite_pct") is not None


async def test_access_water_and_network_in_the_vercors(home):
    """Transports, eau et couverture mobile réels sur une boucle au départ de Lans-en-Vercors."""
    async with server(home) as c:
        lans, moucherotte = {"lat": 45.1279, "lon": 5.5885}, {"lat": 45.1503, "lon": 5.6303}
        route = await call(c, "route_between", {"waypoints": [lans, moucherotte], "loop": True})
        monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
        bus = await call(c, "public_transport", {"route_id": route["route_id"], "date": monday.isoformat(),
                                                 "start_time": "08:30"})  # fmt: skip
        assert bus["depart"]["lignes"] and "Transitous" in bus["source"]
        water = await call(c, "water_and_huts", {"route_id": route["route_id"], "max_distance_m": 800})
        assert any(p["type"] == "point d'eau" for p in water["points"])
        net = await call(c, "mobile_coverage", {"route_id": route["route_id"]})
        assert net["reseau_pct"] is not None and "Arcep" in net["source"]
        fauna = await call(c, "wildlife", {"route_id": route["route_id"], "date": "2026-07-15"})
        assert fauna["groupes"].get("mammifères") and "GBIF" in fauna["source"]
        dossier = await call(c, "prepare_dossier", {"route_id": route["route_id"], "date": monday.isoformat()})
        assert {"météo", "faune", "réseau mobile"} <= set(dossier["sections"]) and not dossier.get("indisponibles")
        assert "leaflet" in Path(dossier["files"]["dossier"]).read_text(encoding="utf-8")
