from datetime import date, time
from pathlib import Path

import gpxpy
import pytest
from mcp import Client

from randoforge.core import areas, stages, weather
from randoforge.core.bivouac import find_spots, slope_from_probes
from randoforge.core.models import (
    AreaCrossing,
    ElevationParams,
    Poi,
    Route,
    RouteRequest,
    TrackPoint,
    WalkerProfile,
    WaySegment,
)
from randoforge.core.osmgeom import RouteFrame
from randoforge.core.quality import assess, marked_share, on_path
from randoforge.core.similarity import deviation, overlap_fraction
from randoforge.core.stats import compute_stats
from randoforge.core.sun import sun_times, timezone_at
from randoforge.formats.gpx import write_gpx
from randoforge.validation import validate

from .test_server import LANS, MOUCHEROTTE, call


def line(n=300, dlat=1e-4, ele=lambda i: 1000.0, lon=6.0):
    """Tracé rectiligne vers le nord, un point tous les ~11 m."""
    return [TrackPoint(lat=45 + i * dlat, lon=lon, ele=ele(i)) for i in range(n)]


def route_of(points, **kw):
    r = Route(route_id="r_2026-10-15_abcdef", name="Test", source="test", points=points, **kw)
    r.stats, _ = compute_stats(points)
    return r


def ids(report):
    return {(c.id, c.level) for c in report.checks}


# --- Soleil ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "rise", "set_"),
    [
        (date(2026, 10, 18), "08:14", "18:56"),
        (date(2026, 12, 21), "08:41", "16:55"),
        (date(2026, 6, 21), "05:46", "21:57"),
    ],
)
def test_sun_times_paris(day, rise, set_):
    tz = timezone_at(48.8566, 2.3522)
    sunrise, sunset = (t.astimezone(tz) for t in sun_times(48.8566, 2.3522, day))
    # Régression : le calcul donnait le lendemain (date julienne prise à midi).
    assert sunrise.date() == sunset.date() == day
    assert abs(int(sunrise.strftime("%H%M")) - int(rise.replace(":", ""))) <= 2
    assert abs(int(sunset.strftime("%H%M")) - int(set_.replace(":", ""))) <= 2


def test_polar_day_has_no_sunset():
    assert sun_times(69.65, 18.96, date(2026, 6, 21)) is None


# --- Zones réglementées -----------------------------------------------------------------


def _square(lat0, lat1, lon0=5.99, lon1=6.01, tags=None, id_=1):
    ring = [(lat0, lon0), (lat1, lon0), (lat1, lon1), (lat0, lon1), (lat0, lon0)]
    return {"type": "way", "id": id_, "tags": tags, "geometry": [{"lat": a, "lon": b} for a, b in ring]}


def test_area_crossing_and_dog_rule():
    pts = line()
    park = _square(45.01, 45.02, tags={"boundary": "national_park", "name": "Parc"})
    military = _square(45.025, 45.026, tags={"landuse": "military"}, id_=2)
    pnr = _square(44.9, 45.1, tags={"boundary": "protected_area", "protect_class": "5", "name": "PNR"}, id_=3)
    found = areas.crossings(pts, [park, military, pnr])
    kinds = {a.kind: a for a in found}
    assert kinds["parc national"].chiens == "interdits"
    assert 1.0 < kinds["parc national"].km_debut < 1.2
    assert "zone militaire" in kinds

    r = route_of(pts, areas=found, request=RouteRequest(with_dog=True))
    rep = validate(r)
    assert ("C1", "error") in ids(rep) and ("A3", "error") in ids(rep)
    assert ("A2", "info") in ids(rep)  # parc naturel régional : simple information


def test_area_fragments_are_merged():
    pts = line()
    frags = [_square(45.010, 45.012, tags={"leisure": "nature_reserve", "name": "R"}, id_=i) for i in (1,)]
    frags.append(_square(45.0125, 45.015, tags={"leisure": "nature_reserve", "name": "R"}, id_=2))
    assert len(areas.crossings(pts, frags)) == 1


# --- Bivouac et étapes --------------------------------------------------------------------


def test_slope_from_probes():
    assert slope_from_probes([100, 100, 100.6, 100, 99.4]) == [4.0]
    assert slope_from_probes([100, None, 100, 100, 100]) == [None]


def test_computed_spots_need_flat_ground_and_no_forbidden_area():
    pts = line(400)
    candidates = [(1000.0, 45.009, 6.0), (2000.0, 45.018, 6.0), (3000.0, 45.027, 6.0)]
    slopes = [3.0, 20.0, 2.0]
    forbidden = AreaCrossing(nom="Réserve", kind="réserve naturelle", km_debut=2.9, km_fin=3.5, bivouac="interdit",
                             osm_id="way/1")  # fmt: skip
    water = Poi(km=1.05, categorie="eau", type="spring", lat=45.0095, lon=6.0, distance_m=5, detour_m=0, score=0.4,
                osm_id="node/1")  # fmt: skip
    spots = find_spots(pts, [], None, candidates, slopes, [], [], [water], [forbidden], [])
    assert [s.km for s in spots] == [1.0]  # trop pentu au km 2, interdit au km 3
    assert spots[0].eau_m < 100 and spots[0].source == "calculé"


def test_plan_stages_balances_days_and_respects_max():
    pts = line(1800, ele=lambda i: 1000 + 30 * ((i // 200) % 2))  # ~20 km
    cuts = [stages.Cut(m=m, label=f"Refuge {m:.0f}", kind="refuge gardé") for m in (5000, 10000, 15000)]
    plan, notes = stages.plan(pts, ElevationParams(), WalkerProfile(), cuts, 2, None, [], [])
    assert len(plan) == 2 and plan[0].arrivee == "Refuge 10000"
    assert abs(plan[0].duree_min - plan[1].duree_min) < 30
    with pytest.raises(ValueError, match="Impossible"):
        stages.plan(pts, ElevationParams(), WalkerProfile(), cuts, 2, 2.0, [], [])
    auto, _ = stages.plan(pts, ElevationParams(), WalkerProfile(), cuts, None, 2.0, [], [])
    # 5 km ≈ 1h20 : deux tronçons dépasseraient 2 h, il faut couper à chaque refuge
    assert len(auto) == 4 and all(s.duree_min <= 120 for s in auto)


# --- Qualité, similarité -------------------------------------------------------------------


def test_on_path_detects_off_trail_section():
    pts = line(300)
    path = {"type": "way", "id": 1, "tags": {"highway": "path"}, "timestamp": "2015-01-01T00:00:00Z",
            "geometry": [{"lat": p.lat, "lon": p.lon} for p in pts[:200]]}  # fmt: skip
    pct, off = on_path(RouteFrame(pts), [path])
    assert 60 < pct < 70 and off and off[0][0] > 2.0
    q = assess(route_of(pts), pct, off, 2015)
    assert q.niveau in {"moyenne", "faible"} and any("OSM" in r for r in q.raisons)


def test_marked_share():
    segs = [
        WaySegment(start_m=0, end_m=300, tags={"route_hiking_lwn": "yes"}),
        WaySegment(start_m=300, end_m=1000, tags={}),
    ]
    assert marked_share(segs) == 30.0


def test_deviation_and_overlap():
    a = line(200)
    shifted = line(200, lon=6.0005)  # ~40 m à l'est
    assert deviation(a, a)[0] == pytest.approx(0, abs=0.01)
    assert deviation(a, shifted)[0] == pytest.approx(39, abs=2)
    assert overlap_fraction(a, a) == pytest.approx(1.0)
    assert overlap_fraction(a, shifted) == 0.0


# --- Météo ---------------------------------------------------------------------------------


def test_weather_summary_and_alerts():
    hours = [f"2026-10-18T{h:02d}:00" for h in range(24)]
    data = {"hourly": {"time": hours, "temperature_2m": [-2] * 24, "precipitation": [1] * 24,
                       "weather_code": [95 if h == 16 else 2 for h in range(24)], "wind_gusts_10m": [70] * 24,
                       "snow_depth": [0.2] * 24, "cape": [0] * 24}}  # fmt: skip
    w = weather.summarize(data, "sommet", 2400.4, range(9, 17))
    assert w.pluie_mm == 8 and w.orage and w.altitude_m == 2400
    alerts = " ".join(weather.alerts([w]))
    assert "orage" in alerts and "Rafales" in alerts and "Neige" in alerts and "Gel" in alerts and "2400 m" in alerts
    assert not weather.summarize(data, "sommet", 2400, range(9, 12)).orage  # orage hors plage de marche


# --- Règles de validation liées à la demande ---------------------------------------------


def test_request_rules():
    pts = line(900, ele=lambda i: 1000 + i)  # ~10 km, ~900 m D+
    req = RouteRequest(target_distance_km=15, target_d_plus_m=900, max_duration_h=2, date=date(2026, 12, 21),
                       start_time=time(15, 0))  # fmt: skip
    r = route_of(pts, request=req)
    found = ids(validate(r))
    assert ("N4", "error") in found  # 10 km au lieu de 15
    assert ("D3", "error") in found
    assert ("D4", "error") in found  # départ 15 h en décembre : arrivée de nuit


def test_daylight_advice_without_start_time():
    r = route_of(line(), request=RouteRequest(date=date(2026, 6, 21)))
    msg = next(c.message for c in validate(r).checks if c.id == "D4")
    assert "partir au plus tard" in msg


def test_season_and_public_rules():
    pts = line(300, ele=lambda i: 2400 + i)
    segs = [WaySegment(start_m=0, end_m=3300, tags={"highway": "path", "sac_scale": "mountain_hiking"})]
    r = route_of(pts, segments=segs, request=RouteRequest(date=date(2026, 1, 10), stroller=True, with_children=True))
    found = ids(validate(r))
    assert ("D5", "warning") in found and ("P1", "error") in found and ("E1", "warning") in found


def test_water_gap_rule():
    r = route_of(line(2000, ele=lambda i: 1000 + (i % 100)))
    r.pois = []
    assert any(c.id == "D6" for c in validate(r).checks)


def test_gpx_per_day_contains_only_that_stage():
    pts = line(900)
    r = route_of(pts)
    r.stages = [
        stages.Stage(jour=1, km_debut=0, km_fin=5, distance_km=5, d_plus_m=0, d_minus_m=0, duree_min=75, duree="1h15",
                     arrivee="Refuge", arrivee_type="refuge gardé"),
        stages.Stage(jour=2, km_debut=5, km_fin=r.stats.distance_km, distance_km=5, d_plus_m=0, d_minus_m=0,
                     duree_min=75, duree="1h15", arrivee="Arrivée", arrivee_type="arrivée"),
    ]  # fmt: skip
    full = gpxpy.parse(write_gpx(r))
    day1 = gpxpy.parse(write_gpx(r, day=1))
    n_full = len(full.tracks[0].segments[0].points)
    n_day1 = len(day1.tracks[0].segments[0].points)
    assert len(full.tracks) == 1 and n_full == len(pts)
    assert n_day1 < n_full * 0.6
    assert any(w.name.startswith("Nuit 1") for w in full.waypoints)


# --- Outils (doublures) ----------------------------------------------------------------------


@pytest.mark.anyio
async def test_trek_workflow(server, tmp_path, soon):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE], "name": "Itinérance"}))[
            "route_id"
        ]
        await call(client, "set_constraints", {"route_id": rid, "with_dog": True, "date": soon.isoformat(),
                                               "start_time": "08:30"})  # fmt: skip

        zones = await call(client, "route_areas", {"route_id": rid})
        assert zones["zones"][0]["kind"] == "parc national"

        q = await call(client, "data_quality", {"route_id": rid})
        assert q["qualite"]["sur_chemin_pct"] == 100 and q["qualite"]["niveau"] == "haute"

        annotated = await call(client, "annotate_route", {"route_id": rid})
        assert any(p["description"] for p in annotated["pois"] if p["wikidata"])

        w = await call(client, "weather_forecast", {"route_id": rid})
        assert len(w["points"]) == 3 and w["heures"].startswith("8h")

        spots = await call(client, "find_bivouac_spots", {"route_id": rid})
        sources = {s["source"] for s in spots["emplacements"]}
        assert {"OSM", "refuges.info"} <= sources

        plan = await call(client, "plan_stages", {"route_id": rid, "days": 2})
        assert len(plan["etapes"]) == 2

        report = await call(client, "validate_route", {"route_id": rid})
        found = {c["id"] for c in report["checks"]}
        assert {"C1", "A2", "D4"} <= found

        bail = await call(client, "bailout_route", {"route_id": rid, "at_km": 3})
        assert "Repli depuis le km 3.0" in bail["name"]

        vault = tmp_path / "vault"
        vault.mkdir()
        files = (await call(client, "export_route", {"route_id": rid, "formats": ["gpx", "md", "html", "roadbook"],
                                                     "vault_dir": str(vault)}))["files"]  # fmt: skip
        assert {"gpx", "gpx_jour_1", "gpx_jour_2", "roadbook", "vault_md"} <= set(files)
        fiche = Path(files["md"]).read_text(encoding="utf-8")
        assert "## Étapes" in fiche and "## Zones réglementées" in fiche and "jours: 2" in fiche
        assert "Où dormir" in Path(files["roadbook"]).read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_history_reference_and_search(server):
    async with Client(server) as client:
        a = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        b = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        await call(client, "mark_done", {"route_id": a, "notes": "super"})
        done = await call(client, "list_routes", {"done": True})
        assert [r["route_id"] for r in done["routes"]] == [a]

        cmp = await call(client, "compare_routes", {"route_ids": [a, b]})
        assert cmp["rows"][1]["deja_fait_pct"] == 100  # b reprend exactement a, qui est fait

        ref = await call(client, "compare_with_reference", {"route_id": b, "reference_id": a})
        assert ref["comparaison"]["ecart_moyen_m"] == pytest.approx(0, abs=0.1)

        routes = await call(client, "find_hiking_routes", {**LANS})
        assert [r["ref"] for r in routes["routes"]][0] == "GR 91"  # réseau national d'abord
        assert len(routes["routes"]) == 2  # relation sans nom ni numéro ignorée

        transport = await call(client, "find_pois", {**LANS, "categories": ["transport"]})
        assert transport["pois"] == [] or all(p["poi"]["categorie"] == "transport" for p in transport["pois"])


@pytest.mark.anyio
async def test_weather_refuses_dates_out_of_range(server):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        res = await client.call_tool("weather_forecast", {"route_id": rid, "date": "2030-01-01"})
        assert res.is_error and "Prévisions disponibles" in res.content[0].text
