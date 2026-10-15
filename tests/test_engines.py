import httpx
import pytest

from randoforge.engines.brouter import parse_geojson
from randoforge.engines.elevation import CopernicusElevation, ElevationChain, IgnElevation
from randoforge.http import CachedHttp, HttpError

from .conftest import load_fixture


def http_with(handler, tmp_path=None):
    return CachedHttp(
        tmp_path / "c.sqlite" if tmp_path else None, transport=httpx.MockTransport(handler), sleep=lambda s: None
    )


def test_brouter_segments_cover_track_length():
    res = parse_geojson(load_fixture("brouter_lans_moucherotte.json"))
    assert res.segments[0].start_m == 0
    assert res.segments[-1].end_m == res.engine_stats["distance_m"] == 7585
    assert all(a.end_m == b.start_m for a, b in zip(res.segments, res.segments[1:], strict=False))
    assert any(s.tags.get("sac_scale") == "mountain_hiking" for s in res.segments)
    assert all(p.ele is None for p in res.points)  # altitude recalculée par notre chaîne


def test_http_fails_over_and_caches(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "down.example":
            return httpx.Response(502)
        return httpx.Response(200, json={"ok": 1})

    http = http_with(handler, tmp_path)
    urls = ["https://down.example/api", "https://up.example/api"]
    assert http.request_json("POST", urls, data={"q": 1}) == {"ok": 1}
    assert http.request_json("POST", urls, data={"q": 1}) == {"ok": 1}  # depuis le cache
    assert calls == ["down.example", "up.example"]


def test_http_client_error_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, text="to-position not mapped in existing datafile")

    with pytest.raises(HttpError, match="not mapped"):
        http_with(handler).request_json("GET", "https://brouter.example", service="BRouter")
    assert len(calls) == 1


def test_http_gives_up_after_retries():
    with pytest.raises(HttpError, match="indisponible après 3 essais"):
        http_with(lambda r: httpx.Response(503)).request_json("GET", "https://x.example")


def test_ign_nodata_becomes_none():
    http = http_with(lambda r: httpx.Response(200, json={"elevations": [995.2, -99999.0]}))
    assert IgnElevation(http).elevations([(45.1, 5.5), (46.0, 7.7)]) == [995.2, None]


def test_chain_falls_back_per_point():
    class Partial:
        name = "A"

        def elevations(self, pts):
            return [1.0 if lat < 46 else None for lat, _ in pts]

    class Full:
        name = "B"

        def elevations(self, pts):
            return [2.0 for _ in pts]

    res = ElevationChain([Partial(), Full()]).elevations([(45, 5), (47, 8), (45.5, 5)])
    assert res.values == [1.0, 2.0, 1.0]
    assert res.summary() == "A 67 %, B 33 %"


@pytest.mark.parametrize(
    ("lat", "lon", "tile"),
    [
        (45.83, 6.86, "Copernicus_DSM_COG_10_N45_00_E006_00_DEM"),
        (-33.9, 18.4, "Copernicus_DSM_COG_10_S34_00_E018_00_DEM"),
        (40.7, -74.0, "Copernicus_DSM_COG_10_N40_00_W074_00_DEM"),
    ],
)
def test_copernicus_tile_names(lat, lon, tile):
    assert CopernicusElevation.tile_name(lat, lon) == tile
