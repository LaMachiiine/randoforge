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
    start = page.index("const d = ")
    data = page[start : page.index("</script>", start)]
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
    assert abs(low - s.d_plus_m * 0.85) <= 1 and high > s.d_plus_m  # les ondulations relèvent le haut
    assert "plausible" in write_fiche(route_of(pts)) and "D+ plausible" in write_roadbook(route_of(pts))


def test_n5_gives_the_range_and_whether_it_contains_the_other_value():
    import math

    from randoforge.validation import validate

    pts = line(900, ele=lambda i: 1000 + 0.5 * i + 3 * math.sin(i / 3))  # D+ 449 m, plausible 381–542 m
    n5 = next(c for c in validate(route_of(pts, engine_stats={"d_plus_m": 540})).checks if c.id == "N5")
    assert "fourchette plausible 381–542 m (contient l'autre valeur)" in n5.message


# --- Relecture finale ---------------------------------------------------------------------------


def test_island_inside_an_enclave_is_back_in_the_area():
    from shapely.geometry import Point

    def ring(d):
        pts = [(45.015 - d, 6 - d), (45.015 + d, 6 - d), (45.015 + d, 6 + d), (45.015 - d, 6 + d), (45.015 - d, 6 - d)]
        return [{"lat": a, "lon": b} for a, b in pts]

    rel = {"type": "relation", "id": 1, "tags": {"boundary": "national_park"},
           "members": [{"role": "outer", "geometry": ring(0.05)}, {"role": "inner", "geometry": ring(0.02)},
                       {"role": "outer", "geometry": ring(0.005)}]}  # fmt: skip
    frame = RouteFrame(line())
    geom = element_geometry(rel, frame.proj)
    inside = lambda lat, lon: geom.contains(Point(*frame.proj.to_xy(lat, lon)))  # noqa: E731
    assert inside(45.015, 6.0) and not inside(45.025, 6.0) and inside(45.05, 6.0)


def test_zone_fragments_are_merged_transitively():
    pts = line(1000)
    tags = {"leisure": "nature_reserve", "name": "R"}
    a, b = _square(45.002, 45.009, tags=tags, id_=1), _square(45.027, 45.036, tags=tags, id_=2)
    c = _square(45.008, 45.028, tags=tags, id_=3)  # relie a et b, arrivé en dernier
    assert len(areas.crossings(pts, [a, b, c])) == 1


def test_d_plus_range_only_for_calibrated_settings():
    from randoforge.core.stats import compute_stats

    pts = line(900, ele=lambda i: 1000 + 0.5 * i)
    assert compute_stats(pts)[0].d_plus_fourchette_m is not None
    custom = ElevationParams(step_m=100, smooth_window_m=500, threshold_m=50)
    assert compute_stats(pts, custom)[0].d_plus_fourchette_m is None


def test_lon_bounds_single_point_on_the_antimeridian():
    from randoforge.core.geo import lon_bounds

    assert lon_bounds([180.0]) == (-180.0, -180.0)
    assert lon_bounds([-180.0, 170.0]) == (170.0, 180.0)


def test_parallel_drafts_follow_the_configured_router():
    from types import SimpleNamespace

    from randoforge.tools.build import PARALLEL_ROUTES, parallel_routes

    def app_with(url):
        return SimpleNamespace(services=SimpleNamespace(router=SimpleNamespace(base_url=url)))

    assert parallel_routes(app_with("https://brouter.de/brouter")) == 2
    assert parallel_routes(app_with("http://localhost:17777/brouter")) == PARALLEL_ROUTES


@pytest.mark.anyio
async def test_legacy_vault_folder_is_renamed_not_duplicated(server, tmp_path):
    from pathlib import Path

    from .test_server import LANS, MOUCHEROTTE, call

    vault = tmp_path / "vault"
    vault.mkdir()
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE], "name": "Ma rando"}))["route_id"]
        # Export fait avec l'ancien nommage (sans identifiant), avec une note ajoutée par l'utilisateur.
        legacy = vault / "Randos" / "Ma rando"
        legacy.mkdir(parents=True)
        (legacy / "fiche.md").write_text(f"---\nroute_id: {rid}\n---\n", encoding="utf-8")
        (legacy / "mes notes.md").write_text("souvenirs", encoding="utf-8")
        other = vault / "Randos" / "Autre"  # dossier d'une autre rando : jamais touché
        other.mkdir()
        (other / "fiche.md").write_text("---\nroute_id: r_2000-01-01_000000\n---\n", encoding="utf-8")
        files = await call(client, "export_route", {"route_id": rid, "formats": ["md"], "vault_dir": str(vault)})
    folder = Path(files["files"]["vault_md"]).parent
    assert not legacy.exists() and (folder / "mes notes.md").read_text(encoding="utf-8") == "souvenirs"
    assert sorted(p.name for p in (vault / "Randos").iterdir()) == ["Autre", folder.name]


# --- Sentiers balisés OSM --------------------------------------------------------------------


def test_chain_route_relation_orients_ways_and_reports_gaps():
    from randoforge.core.osmgeom import chain_route_relation

    def way(*pts, role=""):
        return {"type": "way", "role": role, "geometry": [{"lat": a, "lon": b} for a, b in pts]}

    # Premier chemin à l'envers, deuxième dans le bon sens, troisième à l'envers.
    rel = {"members": [way((45.002, 6), (45.0, 6)), way((45.002, 6), (45.004, 6)), way((45.006, 6), (45.004, 6)),
                       way((45.5, 6), (45.6, 6), role="alternative")]}  # fmt: skip
    line, warnings = chain_route_relation(rel)
    assert line == [(45.0, 6), (45.002, 6), (45.004, 6), (45.006, 6)]
    assert len(warnings) == 1 and "variante" in warnings[0]
    _, warnings = chain_route_relation({"members": [way((45.0, 6), (45.001, 6)), way((45.01, 6), (45.011, 6))]})
    assert "saut" in warnings[0]
    with pytest.raises(ValueError, match="étape"):
        chain_route_relation({"members": [{"type": "relation", "ref": 5}]})


@pytest.mark.anyio
async def test_import_hiking_route_follows_the_marked_trail(server):
    from .test_server import call

    async with Client(server) as client:
        routes = await call(client, "find_hiking_routes", {"lat": 45.13, "lon": 5.59})
        osm_id = next(r["osm_id"] for r in routes["routes"] if r["nom"] == "Boucle locale")
        summary = await call(client, "import_hiking_route", {"osm_id": osm_id})
        assert summary["name"] == "Boucle locale" and summary["stats"]["d_plus_m"] > 0
        assert any("variante" in w for w in summary.get("warnings", []))
        assert summary["source"] == "osm:relation/1"
        res = await client.call_tool("import_hiking_route", {"osm_id": "way/12"})
        assert res.is_error and "relation/123" in res.content[0].text


def test_chain_route_relation_hard_cases():
    from randoforge.core.osmgeom import chain_route_relation

    def way(*pts, role=""):
        return {"type": "way", "role": role, "geometry": [{"lat": a, "lon": b} for a, b in pts]}

    a, b, e, w, c = (45.0, 6.0), (45.0, 6.002), (45.001, 6.001), (44.999, 6.001), (45.0, 5.99)
    # Petite boucle en tête : le 2e chemin touche les deux bouts du 1er ; seul le sens A→…→A évite un saut vers C.
    line, warnings = chain_route_relation({"members": [way(b, e, a), way(b, w, a), way(a, c)]})
    assert line[0] == line[-2] == a and line[-1] == c and not any("saut" in x for x in warnings)
    # Section à sens unique : seul le sens aller est gardé.
    line, warnings = chain_route_relation(
        {"members": [way(a, b), way(b, e, role="forward"), way(e, b, role="backward"), way(e, c)]}
    )
    assert len(line) == 4 and any("sens aller" in x for x in warnings)
    # Boucle à sens unique : les chemins « backward » sont la seule voie, ils sont gardés.
    d = (45.002, 6.0)
    line, warnings = chain_route_relation(
        {
            "members": [
                way(a, b, role="forward"),
                way(e, b, role="backward"),
                way(e, d, role="forward"),
                way(a, d, role="backward"),
            ]
        }  # fmt: skip
    )
    assert line[0] == line[-1] and len(line) == 5 and not warnings
    # Premier chemin court dessiné à l'envers (16 m) : pas d'aller-retour parasite au départ.
    a2 = (45.0, 6.0002)
    line, _ = chain_route_relation({"members": [way(a2, a), way(a2, b)]})
    assert line == [a, a2, b]
    # Relation mixte : sous-itinéraire signalé ; coordonnées nulles ignorées.
    rel = {"members": [way(a, b), {"type": "relation", "ref": 9},
                       {"type": "way", "geometry": [{"lat": None, "lon": 6.0}, {"lat": 45.0, "lon": 6.002}]}]}  # fmt: skip
    _, warnings = chain_route_relation(rel)
    assert any("sous-itinéraire" in x for x in warnings)


def test_unreadable_legacy_fiche_is_ignored(tmp_path):
    from randoforge.tools.output import _exported_from

    legacy = tmp_path / "Ancienne"
    legacy.mkdir()
    (legacy / "fiche.md").write_bytes("---\nroute_id: r_x\nnom: Crête\n".encode("cp1252") + b"\xff")
    assert _exported_from(legacy, "r_x") is False  # pas de l'UTF-8 : ignoré, sans planter


@pytest.mark.anyio
async def test_export_survives_a_locked_legacy_folder(server, tmp_path, monkeypatch):
    from pathlib import Path

    from .test_server import LANS, MOUCHEROTTE, call

    vault = tmp_path / "vault"
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE], "name": "Ma rando"}))["route_id"]
        legacy = vault / "Randos" / "Ma rando"
        legacy.mkdir(parents=True)
        (legacy / "fiche.md").write_text(f"---\nroute_id: {rid}\n---\n", encoding="utf-8")

        def locked(self, target):
            raise PermissionError("dossier ouvert dans Obsidian")

        monkeypatch.setattr(Path, "rename", locked)
        res = await call(client, "export_route", {"route_id": rid, "formats": ["md"], "vault_dir": str(vault)})
    assert Path(res["files"]["vault_md"]).exists() and legacy.exists()


def test_declared_osm_values_are_read_strictly():
    from randoforge.tools.build import declared_values

    assert declared_values({"distance": "8,4 km", "ascent": "650 m"}) == {"distance_m": 8400.0, "d_plus_m": 650.0}
    assert declared_values({"distance": "12500 m", "ascent": "650m"}) == {"distance_m": 12500.0, "d_plus_m": 650.0}
    assert declared_values({"distance": "8"}) == {"distance_m": 8000.0}
    for doubtful in ("12.500 m", "1,200", "8 mi", "env. 8", "650 ft"):
        assert declared_values({"distance": doubtful, "ascent": doubtful}) == {}


# --- Relecture globale finale -------------------------------------------------------------------


def _out_and_back():
    from randoforge.core.models import TrackPoint

    go = [TrackPoint(lat=45 + i * 9e-5, lon=6.0, ele=1000.0) for i in range(500)]  # ~5 km vers le nord
    return go + go[-2::-1]  # retour exact sur les mêmes points


def test_out_and_back_positions_follow_the_walking_order():
    from randoforge.core.pois import annotate

    pts = _out_and_back()
    views = [{"type": "node", "id": i, "lat": 45 + k * 9e-5, "lon": 6.0003, "tags": {"tourism": "viewpoint"}}
             for i, k in enumerate(range(50, 450, 50))]  # fmt: skip
    stream = {"type": "way", "id": 99, "tags": {"waterway": "stream"},
              "geometry": [{"lat": 45.018, "lon": 5.999}, {"lat": 45.018, "lon": 6.001}]}  # fmt: skip
    pois = annotate(pts, [*views, stream], ["point_de_vue", "riviere"], 300)
    kms = [p.km for p in pois if p.categorie == "point_de_vue"]
    assert kms == sorted(kms) and max(kms) < 5  # tous à l'aller, dans l'ordre de marche
    crossings = sorted(p.km for p in pois if p.categorie == "riviere")
    assert len(crossings) == 2 and crossings[0] < 2.1 and crossings[1] > 7.9  # aller et retour


def test_hiking_route_length_reads_units():
    from randoforge.core.osmgeom import declared_values

    assert declared_values({"distance": "5000 m"}) == {"distance_m": 5000.0}  # et non 5000 km


@pytest.mark.anyio
async def test_compute_stats_out_of_range_is_a_clear_error(server):
    from .test_server import LANS, MOUCHEROTTE, call

    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        res = await client.call_tool("compute_stats", {"route_id": rid, "step_m": 0})
    assert res.is_error and "Paramètre hors bornes" in res.content[0].text


@pytest.mark.anyio
async def test_import_warnings_survive_a_stats_recompute(server):
    from .test_server import call

    async with Client(server) as client:
        rid = (await call(client, "import_hiking_route", {"osm_id": "relation/1"}))["route_id"]
        again = await call(client, "compute_stats", {"route_id": rid, "walker": "famille"})
    assert any("variante" in w for w in again.get("warnings", []))


def test_daylight_reports_both_dark_start_and_dark_arrival():
    from datetime import date, time

    from randoforge.core.models import RouteRequest
    from randoforge.validation import validate

    pts = line(5000, ele=lambda i: 1000 + i // 5)  # ~55 km : arrivée bien après le coucher du soleil
    r = route_of(pts, request=RouteRequest(date=date(2026, 10, 20), start_time=time(6, 0)))
    d4 = [c for c in validate(r).checks if c.id == "D4"]
    assert {c.level for c in d4} == {"warning", "error"}


def test_gpx_stays_valid_with_control_characters():
    import gpxpy

    from randoforge.formats.gpx import write_gpx

    r = route_of(line())
    r.name = "Crête\x0bdu\x01Moucherotte"
    assert gpxpy.parse(write_gpx(r)).tracks[0].name == "CrêteduMoucherotte"


@pytest.mark.anyio
async def test_bivouac_ban_stays_on_the_spots_it_concerns(server, monkeypatch):
    from randoforge.core.models import BivouacSpot

    from .test_server import LANS, MOUCHEROTTE, call

    ban = "Bivouac probablement interdit (réserve naturelle) : vérifier le règlement"

    def fake(app, route):
        route.bivouacs = [
            BivouacSpot(km=2 + k / 2, lat=45.1, lon=5.6, source="calculé", type="emplacement possible", score=0.5,
                        avertissements=["À vérifier sur place"] + ([ban] if k < 3 else []))
            for k in range(6)  # km 2 à 4,5 : au milieu du tracé de ~7,6 km, là où une nuit a du sens
        ]  # fmt: skip
        return []

    monkeypatch.setattr("randoforge.tools.trek.compute_bivouacs", fake)
    async with Client(server) as client:
        rid = (await call(client, "route_between", {"waypoints": [LANS, MOUCHEROTTE]}))["route_id"]
        res = await call(client, "find_bivouac_spots", {"route_id": rid})
    banned = [s["km"] for s in res["emplacements"] if ban in s.get("avertissements", [])]
    assert banned == [2.0, 2.5, 3.0] and ban not in res["rappels"] and "À vérifier sur place" in res["rappels"]


# --- Randos reconstruites et catalogues officiels -----------------------------------------------


@pytest.mark.anyio
async def test_route_via_places_never_guesses_far_places(server):
    from .test_server import LANS, call

    async with Client(server) as client:
        res = await call(client, "route_via_places", {"start": LANS, "places": ["Moucherotte", "Lyon"], "loop": True})
        assert [p["lieu"] for p in res["lieux"]] == ["Moucherotte"] and res["non_trouves"] == ["Lyon"]
        assert res["route"]["stats"]["distance_km"] > 0
        assert any("Lyon" in w for w in res["route"]["warnings"])
        err = await client.call_tool("route_via_places", {"start": LANS, "places": ["Lyon"]})
        assert err.is_error and "Aucun lieu trouvé" in err.content[0].text


def test_catalog_registry_covers_many_official_catalogues():
    from randoforge.engines.geotrek import CATALOGS, catalogs_near, is_walking

    assert len(CATALOGS) >= 40 and {"ecrins", "cevennes", "portcros"} <= set(CATALOGS)
    assert "vercors" in catalogs_near(45.07, 5.55) and "ecrins" not in catalogs_near(45.07, 5.55)
    assert is_walking("A pied") and is_walking("Pédestre") and is_walking("Randonnée")
    assert not is_walking("VTT") and not is_walking("Trail") and not is_walking("Raquette")


def test_polyline_filter_terminates_on_a_self_crossing_route():
    """Tracé réel d'un agent (22,9 km, recoupements) : la simplification topologique plafonnait à 263 sommets et
    la boucle « tant que > 150 sommets » ne finissait jamais (serveur bloqué en plein validate_route)."""
    import json
    import time
    from pathlib import Path

    from randoforge.core.models import TrackPoint

    coords = json.loads((Path(__file__).parent / "fixtures" / "route_recoupee.json").read_text(encoding="utf-8"))
    frame = RouteFrame([TrackPoint(lat=a, lon=b) for a, b in coords])
    t0 = time.perf_counter()
    q = frame.polyline_filter(100)
    assert time.perf_counter() - t0 < 2 and q.count(",") // 2 <= 150
    radius = float(q.split(",")[0].removeprefix("around:"))
    assert radius >= 100 + frame.line.hausdorff_distance(frame.line.simplify(5, preserve_topology=False)) - 1


def test_best_sequence_prefers_coherent_homonyms():
    from randoforge.core.places import best_sequence

    start = (44.10, 3.78)
    # « Saint-Roman » : un hameau voisin et un village homonyme à 10 km ; « Cabrijoule » entre les deux étapes.
    saint_roman = [(44.19, 3.78), (44.12, 3.79)]
    cabrijoule = [(44.115, 3.80)]
    assert best_sequence(start, [saint_roman, cabrijoule], start) == [1, 0]
    assert best_sequence(start, [], None) == []


def test_isolated_place_is_flagged_but_a_single_summit_is_not():
    from randoforge.core.places import outliers

    start = (44.108, 3.783)
    route = [(44.12, 3.79), (44.197, 3.78), (44.115, 3.80), (44.110, 3.785)]  # le 2e : homonyme à ~10 km
    assert outliers(start, route, start, 3.0) == [1]
    assert outliers(start, [(44.15, 3.83)], start, 3.0) == []  # boucle vers un seul sommet : légitime


def test_n1_tolerates_the_normal_gap_of_a_low_relief_loop():
    from randoforge.core.stats import loop_gap_excess

    # Boucle réelle de Clohars-Carnoët : D+ 169 m / D- 172 m, départ = arrivée (39 m) → écart normal (≤ 2 × 5 m).
    assert loop_gap_excess(169, 172, 39.3, 39.3, 5.0) == 0
    # Écart de 40 m sans différence d'altitude aux bouts : vraie incohérence.
    assert loop_gap_excess(400, 360, 1000, 1000, 5.0) == 30
    # Boucle refermée à 50 m près mais 12 m plus bas : l'écart correspondant est normal.
    assert loop_gap_excess(300, 312, 1012, 1000, 5.0) == 0


# --- Épingles des boucles générées --------------------------------------------------------------


def test_spur_to_an_attraction_point_is_removed_but_a_wanted_one_is_kept():
    from randoforge.core.loops import remove_spurs
    from randoforge.core.models import TrackPoint, WaySegment

    def p(lat, lon):
        return TrackPoint(lat=lat, lon=lon)

    # Départ → A → pointe d'un chemin en impasse (≈ 330 m aller-retour) → A → suite de la boucle.
    a, tip = p(45.0, 6.0), p(45.0015, 6.0)
    pts = [p(44.999, 6.0), a, p(45.0008, 6.0), tip, p(45.0008, 6.0), a, p(45.0, 6.002), p(44.99, 6.002),
           p(44.99, 6.0), p(44.999, 6.0)]  # fmt: skip
    segs = [WaySegment(start_m=0, end_m=10_000, tags={"highway": "path"})]
    out, new_segs, cut = remove_spurs(pts, segs, [(44.999, 6.0)])
    assert out == [pts[0], a, *pts[6:]] and 320 < cut < 340
    assert new_segs[-1].end_m < 10_000  # tronçons recalés sur le tracé raccourci
    # Même épingle, mais vers un point imposé (sommet choisi) : conservée.
    kept, _, cut = remove_spurs(pts, segs, [(44.999, 6.0), (45.0015, 6.0)])
    assert kept == pts and cut == 0


def test_only_spots_placed_logically_for_a_night_are_offered():
    from randoforge.core.bivouac import night_window, useful_for_night
    from randoforge.core.models import BivouacSpot, Stage

    def spot(km):
        return BivouacSpot(km=km, lat=45.0, lon=6.0, source="OSM", type="camping")

    spots = [spot(k) for k in (2, 5.5, 11.4, 15, 21.7, 26.4, 30)]
    assert night_window(30.9) == (7.725, 23.174999999999997)
    assert [b.km for b in useful_for_night(spots, 30.9)] == [11.4, 15, 21.7]  # ni km 2-5 ni km 26-30
    nights = [Stage(jour=1, km_debut=0, km_fin=14, distance_km=14, d_plus_m=0, d_minus_m=0, duree_min=0, duree="",
                    arrivee="x", arrivee_type="bivouac"),
              Stage(jour=2, km_debut=14, km_fin=30.9, distance_km=16.9, d_plus_m=0, d_minus_m=0, duree_min=0,
                    duree="", arrivee="y", arrivee_type="arrivée")]  # fmt: skip
    assert [b.km for b in useful_for_night(spots, 30.9, nights)] == [11.4, 15]  # près de la nuit prévue (km 14)


def test_out_and_back_to_an_imposed_point_is_reported():
    from randoforge.core.loops import spur_notes
    from randoforge.core.models import TrackPoint

    def p(lat, lon):
        return TrackPoint(lat=lat, lon=lon)

    summit = (45.006, 6.0)  # sommet au bout d'une impasse de ~670 m
    pts = [p(44.99, 6.0), p(45.0, 6.0), p(45.003, 6.0), p(*summit), p(45.003, 6.0), p(45.0, 6.0), p(45.0, 6.01),
           p(44.99, 6.01), p(44.99, 6.0)]  # fmt: skip
    notes = spur_notes(pts, [(44.99, 6.0), summit])
    assert len(notes) == 1 and "1.3 km" in notes[0] and "point de passage n°2" in notes[0]


def test_repeated_checks_are_merged_and_errors_listed_first():
    from randoforge.core.models import Check, ValidationReport
    from randoforge.validation import alert_lines, merge_repeats

    ford = "Gué : vérifier le niveau d'eau"
    merged = merge_repeats([Check(id="D7", level="warning", km=7.4, message=ford),
                            Check(id="D7", level="warning", km=3.1, message=ford),
                            Check(id="D7", level="warning", km=5.0, message="Gué sur le Furon : vérifier")])  # fmt: skip
    assert len(merged) == 2 and merged[0].km == 3.1 and merged[0].message.endswith("2 fois : km 3.1, 7.4")
    checks = [Check(id=f"W{i}", level="warning", message="w") for i in range(12)] + [
        Check(id="C1", level="error", message="chien interdit")
    ]
    assert alert_lines(ValidationReport(status="error", checks=checks), 8)[0] == "C1 : chien interdit"


def test_steep_passages_fit_in_one_line(monkeypatch):
    from types import SimpleNamespace

    from randoforge import validation
    from randoforge.core.terrain import Section as Sec

    secs = [Sec(start_m=1000 * k, end_m=1000 * k + 150, value=v) for k, v in enumerate((37, 71, 40))]
    monkeypatch.setattr(validation, "steep_sections", lambda *a: secs)
    (check,) = validation.check_slopes(SimpleNamespace(points=[]))
    assert (
        check.message.startswith("3 passages raides, le plus raide : jusqu'à 71 %") and "km 2.0 (40 %)" in check.message
    )


def test_same_place_seen_twice_is_listed_once():
    from randoforge.core.models import Check
    from randoforge.validation import merge_repeats

    (only,) = merge_repeats([Check(id="D7", level="warning", km=7.61, message="Gué"),
                             Check(id="D7", level="warning", km=7.64, message="Gué")])  # fmt: skip
    assert only.message == "Gué"
