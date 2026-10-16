"""Cas limites relevés par la revue de code : sources en panne, géométries OSM, formats, étapes."""

import httpx
import pytest
from mcp import Client

from randoforge.core import areas, stages
from randoforge.core.bivouac import find_spots
from randoforge.core.models import ElevationParams, WalkerProfile
from randoforge.core.osmgeom import RouteFrame, element_geometry
from randoforge.engines.elevation import ElevationChain
from randoforge.formats.html import write_map
from randoforge.formats.markdown import write_fiche
from randoforge.formats.roadbook import write_roadbook
from randoforge.http import CachedHttp, HttpError

from .test_phase3 import _square, line, route_of

# --- Sources externes ------------------------------------------------------------------------


def test_blocked_mirror_does_not_stop_the_others():
    def handler(request):
        if request.url.host == "a.example":
            return httpx.Response(403, text="Forbidden")
        return httpx.Response(200, json={"ok": 1})

    http = CachedHttp(None, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert http.request_json("POST", ["https://a.example/i", "https://b.example/i"], data={"q": "1"}) == {"ok": 1}


def test_invalid_url_is_reported_not_retried():
    http = CachedHttp(None, transport=httpx.HTTPTransport(), sleep=lambda s: None)
    with pytest.raises(HttpError, match="adresse invalide"):
        http.request_json("GET", "overpass.example/api", service="Overpass")


def test_elevation_chain_falls_back_when_a_source_is_down():
    class Down:
        name = "IGN"

        def elevations(self, pts):
            raise HttpError("Altimétrie IGN indisponible")

    class Backup:
        name = "Copernicus"

        def elevations(self, pts):
            return [500.0 for _ in pts]

    res = ElevationChain([Down(), Backup()]).elevations([(45, 5), (45.1, 5)])
    assert res.values == [500.0, 500.0] and "IGN" in res.errors[0]
    with pytest.raises(ValueError, match="Altimétrie indisponible"):
        ElevationChain([Down()]).elevations([(45, 5)])


# --- Géométries et zones -----------------------------------------------------------------------


def test_multipolygon_enclave_is_excluded():
    outer = [(45.00, 5.99), (45.03, 5.99), (45.03, 6.01), (45.00, 6.01), (45.00, 5.99)]
    hole = [(45.01, 5.995), (45.02, 5.995), (45.02, 6.005), (45.01, 6.005), (45.01, 5.995)]
    rel = {
        "type": "relation",
        "id": 9,
        "tags": {"boundary": "national_park", "name": "Parc"},
        "members": [
            {"role": "outer", "geometry": [{"lat": a, "lon": b} for a, b in outer]},
            {"role": "inner", "geometry": [{"lat": a, "lon": b} for a, b in hole]},
        ],
    }
    frame = RouteFrame(line())
    geom = element_geometry(rel, frame.proj)
    x, y = frame.proj.to_xy(45.015, 6.0)
    from shapely.geometry import Point

    assert not geom.contains(Point(x, y))  # le village exclu n'est pas dans le parc
    found = areas.crossings(line(), [rel])
    assert len(found) == 2  # le tracé entre, sort (enclave), puis rentre


def test_distant_unnamed_zones_are_not_merged():
    pts = line(1000)  # ~11 km vers le nord
    far = _square(45.085, 45.092, tags={"landuse": "military"}, id_=1)
    near = _square(45.014, 45.021, tags={"landuse": "military"}, id_=2)
    found = areas.crossings(pts, [far, near])  # ordre Overpass : la plus lointaine d'abord
    assert len(found) == 2 and min(a.km_debut for a in found) < 2.5


# --- Étapes et bivouacs ------------------------------------------------------------------------


def test_last_stage_without_water_is_reported():
    pts = line(900)
    plan, notes = stages.plan(pts, ElevationParams(), WalkerProfile(), [], 1, None, [], [])
    assert len(plan) == 1 and any("Jour 1 : aucun point d'eau" in n for n in notes)


def test_computed_spot_without_road_data_does_not_claim_far_from_roads():
    pts = line(400)
    spots = find_spots(pts, [], None, [(1000.0, 45.009, 6.0)], [2.0], [], [], [], [], [])
    assert spots and not any("loin des routes" in w for w in spots[0].avertissements)
    assert any("distance aux routes inconnue" in w for w in spots[0].avertissements)


# --- Formats ---------------------------------------------------------------------------------


def test_osm_names_cannot_break_the_map_or_the_fiche():
    r = route_of(line())
    r.stages = [stages.Stage(jour=1, km_debut=0, km_fin=1, distance_km=1, d_plus_m=0, d_minus_m=0, duree_min=15,
                             duree="0h15", arrivee="<!--<script>", arrivee_type="refuge"),
                stages.Stage(jour=2, km_debut=1, km_fin=3, distance_km=2, d_plus_m=0, d_minus_m=0, duree_min=30,
                             duree="0h30", arrivee="Fin", arrivee_type="arrivée")]  # fmt: skip
    page = write_map(r)
    data = page[page.index("const d = ") : page.index("</script></body>")]
    assert "Nuit 1" in data and "<" not in data.split(";")[0]
    r.name = "<iframe src=x>"
    assert "<iframe" not in write_fiche(r)


def test_zero_d_plus_is_shown_as_zero_and_missing_values_as_unknown():
    r = route_of(line())  # tracé plat : D+ = 0
    assert "0 / 0 m" in write_roadbook(r) and "?" not in write_map(r).split("<header>")[1].split("</header>")[0]
    r.stats.alt_min_m = r.stats.alt_max_m = None
    assert "None" not in write_roadbook(r)


# --- Outils ----------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unreadable_gpx_gives_a_clear_error(server, tmp_path):
    bad = tmp_path / "trace.gpx"
    bad.write_text("<gpx><trk>pas fini", encoding="utf-8")
    async with Client(server) as client:
        res = await client.call_tool("import_gpx", {"path": str(bad)})
    assert res.is_error and "GPX illisible" in res.content[0].text


def test_retry_rounds_stop_when_the_time_budget_is_spent(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("randoforge.http.time.time", lambda: clock[0])

    def handler(request):
        clock[0] += 100  # chaque tour coûte 100 s (serveur qui finit par expirer)
        return httpx.Response(504)

    http = CachedHttp(None, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(HttpError, match="pas de réponse en 180 s"):
        http.request_json("GET", "https://x.example", attempts=6, budget_s=180)
    assert clock[0] == 200  # deux tours, pas six


# --- Antiméridien ------------------------------------------------------------------------------


def test_track_across_the_antimeridian():
    import numpy as np

    from randoforge.core.geo import densify, lon_bounds, resample
    from randoforge.core.models import TrackPoint
    from randoforge.core.pois import bbox_around

    lats, lons = np.array([-16.8, -16.8]), np.array([179.999, -179.999])  # ~210 m à travers ±180°
    dl, dn = densify(lats, lons, 10)
    assert 20 <= len(dn) <= 30 and np.all(np.abs(dn) > 179.99)  # pas de détour par le méridien de Greenwich
    _, _, rl, _ = resample(lats, lons, np.array([0.0, 0.0]), 10)
    assert np.all(np.abs(rl) > 179.99)
    w, e = lon_bounds(lons)
    assert w > e and w > 179.9 and e < -179.9  # convention Overpass : ouest > est
    s, w, n, e = bbox_around([TrackPoint(lat=-16.8, lon=179.999), TrackPoint(lat=-16.8, lon=-179.999)], 100)
    assert w > e


def test_densify_keeps_original_points_and_max_step():
    import numpy as np

    from randoforge.core.geo import densify, segment_lengths

    lats, lons = np.array([45.0, 45.001, 45.0011]), np.array([6.0, 6.002, 6.0021])
    dl, dn = densify(lats, lons, 10)
    assert dl[0] == 45.0 and dl[-1] == 45.0011 and segment_lengths(dl, dn).max() <= 10.01
    assert any(abs(a - 45.001) < 1e-12 and abs(b - 6.002) < 1e-12 for a, b in zip(dl, dn, strict=True))


# --- Fourchette de D+ ---------------------------------------------------------------------------


def test_d_plus_range_brackets_the_retained_value():
    import math

    from randoforge.core.stats import compute_stats

    # Montée régulière + petites ondulations de 3 m, sous le seuil d'hystérésis de 5 m.
    pts = line(900, ele=lambda i: 1000 + 0.5 * i + 3 * math.sin(i / 3))
    s, _ = compute_stats(pts)
    low, high = s.d_plus_fourchette_m
    assert abs(low - s.d_plus_m * 0.93) <= 1 and high > s.d_plus_m  # les ondulations relèvent le haut
    assert "plausible" in write_fiche(route_of(pts)) and "D+ plausible" in write_roadbook(route_of(pts))


def test_n5_gives_the_range_and_whether_it_contains_the_other_value():
    import math

    from randoforge.validation import validate

    pts = line(900, ele=lambda i: 1000 + 0.5 * i + 3 * math.sin(i / 3))  # D+ 449 m, plausible 417–542 m
    n5 = next(c for c in validate(route_of(pts, engine_stats={"d_plus_m": 540})).checks if c.id == "N5")
    assert "fourchette plausible 417–542 m (contient l'autre valeur)" in n5.message
