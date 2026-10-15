import httpx
import pytest
from mcp import Client

from randoforge.core.bivouac import find_spots
from randoforge.core.models import Poi, Route, TrackPoint
from randoforge.core.stats import compute_stats
from randoforge.engines.geotrek import GeotrekReference
from randoforge.http import CachedHttp
from randoforge.validation import validate

from .test_server import LANS, MOUCHEROTTE, call


def line(n=300, ele=lambda i: 1000.0):
    return [TrackPoint(lat=45 + i * 1e-4, lon=6.0, ele=ele(i)) for i in range(n)]


# --- N2 : sommets tronqués par le MNT ------------------------------------------------


def _route_with_peak(official_ele: float) -> Route:
    pts = line(200, ele=lambda i: 2000 + min(i, 200 - i) * 5)  # sommet au milieu, MNT : 2500 m
    r = Route(route_id="r_2026-10-15_abcdef", name="t", source="t", points=pts)
    r.stats, _ = compute_stats(pts)
    top = pts[100]
    r.pois = [Poi(km=r.stats.distance_km / 2, categorie="sommet", type="peak", nom="Pic", lat=top.lat, lon=top.lon,
                  distance_m=5, detour_m=0, score=0.8, ele=official_ele, osm_id="node/1")]  # fmt: skip
    return r


def test_sharp_summit_underestimated_by_dem_is_flagged():
    checks = [c for c in validate(_route_with_peak(2560)).checks if c.id == "N2"]
    assert checks and "60 m" in checks[0].message and checks[0].level == "warning"


def test_summit_close_to_dem_is_not_flagged():
    assert not [c for c in validate(_route_with_peak(2505)).checks if c.id == "N2"]


# --- Bivouac abrité -----------------------------------------------------------------------


def test_caves_and_natural_shelters_are_sheltered_spots():
    pts = line(400)
    cave = {
        "type": "node",
        "id": 1,
        "lat": 45.01,
        "lon": 6.0003,
        "tags": {"natural": "cave_entrance", "name": "Grotte"},
    }
    rock = {
        "type": "node",
        "id": 2,
        "lat": 45.02,
        "lon": 6.0002,
        "tags": {"amenity": "shelter", "shelter_type": "rock_shelter"},
    }
    camp = {
        "type": "node",
        "id": 3,
        "lat": 45.03,
        "lon": 6.0001,
        "tags": {"tourism": "camp_site", "backcountry": "yes"},
    }
    natural = {
        "id": 4,
        "nom": "Baume",
        "type": "abri naturel",
        "lat": 45.035,
        "lon": 6.0,
        "alt": 1500,
        "places": 2,
        "lien": None,
    }
    spots = find_spots(pts, [], None, [], [], [cave, rock, camp], [natural], [], [], [])
    by_type = {s.type: s for s in spots}
    assert by_type["grotte"].abrite and by_type["abri sous roche"].abrite
    assert by_type["abri naturel (grotte, abri sous roche)"].abrite
    assert not by_type["aire de bivouac / camping"].abrite
    assert any("chauves-souris" in w for w in by_type["grotte"].avertissements)


@pytest.mark.anyio
async def test_sheltered_only_filter_and_stage_option(server):
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        spots = await call(client, "find_bivouac_spots", {"route_id": rid, "abrite_seulement": True})
        assert spots["emplacements"] and all(s["abrite"] for s in spots["emplacements"])
        plan = await call(client, "plan_stages", {"route_id": rid, "days": 2, "overnight": "abri"})
        assert plan["etapes"][0]["arrivee_type"] in {"cabane", "refuge gardé", "abri", "grotte", "abri sous roche"}


# --- Référence Geotrek ------------------------------------------------------------------------


def test_geotrek_reference_keeps_only_walking_line_treks():
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        if "trek_practice" in request.url.path:
            return httpx.Response(200, json={"results": [{"id": 2, "name": "VTT"}, {"id": 4, "name": "A pied"}]})
        line_geom = {"type": "LineString", "coordinates": [[6.0, 45.0, 1000.0], [6.01, 45.0, 1100.0]]}
        return httpx.Response(200, json={"count": 3, "results": [
            {"id": 1, "name": {"fr": "Boucle"}, "ascent": 300, "descent": -300, "length_2d": 5000, "geometry": line_geom},
            {"id": 2, "name": "Sans D+", "ascent": 0, "length_2d": 5000, "geometry": line_geom},
            {"id": 3, "name": "Multi", "ascent": 100, "length_2d": 5000, "geometry": {"type": "MultiLineString", "coordinates": []}},
        ]})  # fmt: skip

    http = CachedHttp(None, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    treks = GeotrekReference(http).treks("ecrins", 5)
    assert [t.name for t in treks] == ["Boucle"]
    assert treks[0].descent_m == 300 and treks[0].coords[0] == (45.0, 6.0, 1000.0)
    assert calls[1]["practices"] == "4"  # seulement la randonnée pédestre
