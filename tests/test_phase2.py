import pytest
from mcp import Client

from randoforge.core import loops
from randoforge.core.geo import distance_m
from randoforge.core.models import TrackPoint, WaySegment
from randoforge.core.technical import merge, osm_clues, segment_clues, technical_passages
from randoforge.core.terrain import retraced_sections, steep_sections

from .test_server import LANS, call


def line(n, dlat=1e-4, ele=lambda i: 1000.0):
    """Tracé rectiligne vers le nord, un point tous les ~11 m."""
    return [TrackPoint(lat=45 + i * dlat, lon=6.0, ele=ele(i)) for i in range(n)]


# --- Terrain ------------------------------------------------------------------------


def test_steep_section_detected_only_where_steep():
    # 1 km plat, puis 300 m à 50 %, puis plat
    def ele(i):
        return 1000 + 0.5 * 11.1 * min(max(i - 90, 0), 27)

    sections = steep_sections(line(200, ele=ele))
    assert len(sections) == 1
    assert sections[0].value == pytest.approx(50, abs=3)
    assert 900 < sections[0].start_m < 1100


def test_out_and_back_is_retraced_but_loop_is_not():
    aller = line(100)
    assert sum(s.value for s in retraced_sections(aller + aller[-2::-1])) > 700
    # Boucle carrée : ne repasse jamais au même endroit
    side = [(45 + i * 1e-4, 6.0) for i in range(50)]
    side += [(45.005, 6 + i * 1.4e-4) for i in range(50)]
    side += [(45.005 - i * 1e-4, 6.007) for i in range(50)]
    side += [(45.0, 6.007 - i * 1.4e-4) for i in range(51)]
    square = [TrackPoint(lat=a, lon=b, ele=1000) for a, b in side]
    assert retraced_sections(square) == []


# --- Passages techniques --------------------------------------------------------------


def test_segment_clues_keep_t3_and_above():
    segs = [
        WaySegment(start_m=0, end_m=100, tags={"sac_scale": "mountain_hiking"}),
        WaySegment(start_m=100, end_m=250, tags={"sac_scale": "demanding_mountain_hiking"}),
        WaySegment(start_m=250, end_m=300, tags={"sac_scale": "alpine_hiking"}),
    ]
    clues = segment_clues(segs, scale=1.0)
    assert [c.level for c in clues] == [3, 4]
    merged = merge(clues)
    assert len(merged) == 1 and merged[0].niveau == "T4" and merged[0].longueur_m == 200


def test_osm_clues_ladder_on_route_and_ignores_parallel_path():
    pts = line(100)
    on_route = {
        "type": "way",
        "id": 1,
        "tags": {"highway": "path", "ladder": "yes"},
        "geometry": [{"lat": 45.003, "lon": 6.0}, {"lat": 45.004, "lon": 6.0}],
    }
    # Chemin parallèle à ~80 m à l'est : ne doit pas compter
    parallel = {
        "type": "way",
        "id": 2,
        "tags": {"highway": "path", "safety_rope": "yes"},
        "geometry": [{"lat": 45.003, "lon": 6.001}, {"lat": 45.004, "lon": 6.001}],
    }
    clues = osm_clues(pts, [on_route, parallel])
    assert [c.kind for c in clues] == ["échelle"]
    assert 300 < clues[0].start_m < 360


def test_glacier_polygon_crossed():
    pts = line(100)
    ring = [(44.9995, 5.999), (45.0055, 5.999), (45.0055, 6.001), (44.9995, 6.001), (44.9995, 5.999)]
    glacier = {
        "type": "way",
        "id": 3,
        "tags": {"natural": "glacier"},
        "geometry": [{"lat": a, "lon": b} for a, b in ring],
    }
    passages = technical_passages(pts, [], [glacier], None)
    assert passages and "glacier" in passages[0].types and passages[0].niveau == "T5"


def test_extreme_slope_on_easy_path_is_flagged_suspicious():
    def ele(i):
        return 1000 + 0.8 * 11.1 * min(max(i - 40, 0), 20)  # 80 % sur ~220 m

    pts = line(100, ele=ele)
    segs = [WaySegment(start_m=0, end_m=1200, tags={"highway": "path", "sac_scale": "hiking"})]
    passages = technical_passages(pts, segs, [], 1100)
    assert passages and passages[0].a_verifier


# --- Boucles -------------------------------------------------------------------------


def test_triangle_is_equilateral_and_closed():
    start = (45.0, 6.0)
    wps = loops.triangle(start, 90, 2000)
    assert wps[0] == wps[-1] == start
    assert distance_m(start, wps[1]) == pytest.approx(2000, rel=1e-6)
    assert distance_m(wps[1], wps[2]) == pytest.approx(2000, rel=0.01)


def test_radius_correction_is_bounded():
    assert loops.corrected_radius(1000, 10_000, 20_000) == 500
    assert loops.corrected_radius(1000, 10_000, 1_000) == 2000  # borné à ×2


def test_score_prefers_closer_and_penalises_retrace():
    good = loops.score(10_000, 10_000, 500, 500, 0, 0)
    retraced = loops.score(10_000, 10_000, 500, 500, 3_000, 0)
    off = loops.score(13_000, 10_000, 500, 500, 0, 0)
    assert good.total < off.total < retraced.total


# --- Outils du serveur ------------------------------------------------------------------


@pytest.mark.anyio
async def test_generate_loop_candidates(server, services):
    async with Client(server) as client:
        res = await call(client, "generate_loop_candidates", {"start": LANS, "distance_km": 8, "n": 2, "directions": 4})
        assert len(res["candidates"]) == 2
        assert res["tried"] >= 4
        names = [c["route"]["name"] for c in res["candidates"]]
        assert names[0].startswith("Boucle 1")
        # chaque essai part et revient au départ
        assert all(w[0] == w[-1] == (45.1279, 5.5885) for w, _ in services.router.calls)

        ids = [c["route"]["route_id"] for c in res["candidates"]]
        cmp = await call(client, "compare_routes", {"route_ids": ids})
        assert [r["route_id"] for r in cmp["rows"]] == ids


@pytest.mark.anyio
async def test_technical_passages_and_walker_presets(server):
    async with Client(server) as client:
        route = await call(client, "route_between", {"waypoints": [LANS, {"lat": 45.1503, "lon": 5.6303}]})
        rid = route["route_id"]
        tech = await call(client, "technical_passages", {"route_id": rid})
        kms = [p["km"] for p in tech["passages"]]
        assert kms == sorted(kms)

        famille = await call(client, "compute_stats", {"route_id": rid, "walker": "famille"})
        sportif = await call(client, "compute_stats", {"route_id": rid, "walker": "sportif"})
        assert famille["stats"]["duration_min"] > sportif["stats"]["duration_min"]

        files = (await call(client, "export_route", {"route_id": rid}))["files"]
        assert set(files) == {"gpx", "md", "html"}
