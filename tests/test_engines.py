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


def test_hedged_request_takes_first_valid_answer_without_waiting_for_slow_server():
    import time as _time

    def handler(request):
        if request.url.host == "slow.example":
            _time.sleep(2)
            return httpx.Response(200, json={"elements": [1]})
        return httpx.Response(200, json={"elements": [2]})

    http = http_with(handler)
    t0 = _time.time()
    res = http.request_json(
        "POST", ["https://slow.example/i", "https://fast.example/i"], data={"q": 1}, hedge_after_s=0.2
    )
    assert res == {"elements": [2]} and _time.time() - t0 < 1.5


def test_overpass_runtime_error_in_200_is_not_an_empty_result():
    from randoforge.engines.osm import Overpass

    def handler(request):
        if request.url.host == "broken.example":
            return httpx.Response(200, json={"elements": [], "remark": "runtime error: Query timed out"})
        return httpx.Response(200, json={"elements": [{"id": 1}]})

    over = Overpass(http_with(handler), ["https://broken.example/i", "https://ok.example/i"])
    assert over.query("q") == [{"id": 1}]


def test_unreachable_server_is_set_aside():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "dead.example":
            raise httpx.ConnectTimeout("timeout")
        return httpx.Response(200, json={"ok": 1})

    http = http_with(handler)
    for i in range(3):
        http.request_json("GET", ["https://dead.example/a", "https://up.example/a"], params={"i": i})
    assert calls.count("dead.example") == 1  # essayé une fois, puis écarté


def test_too_slow_brouter_is_retried_once_then_explained():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, text="operation killed by thread-priority-watchdog after 2 seconds")

    with pytest.raises(HttpError, match="rapprocher les points"):
        http_with(handler).request_json("GET", "https://brouter.example", service="BRouter")
    assert len(calls) == 2  # une nouvelle chance (surcharge passagère), pas trois


def test_single_server_is_not_set_aside_after_connect_error():
    answers = iter([httpx.ConnectTimeout("t"), httpx.Response(200, json={"ok": 1})])

    def handler(request):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a

    assert http_with(handler).request_json("GET", "https://ign.example") == {"ok": 1}


def test_overloaded_brouter_400_is_retried():
    answers = iter([httpx.Response(400, text="operation killed by thread-priority-watchdog after 2 seconds"),
                    httpx.Response(200, json={"ok": 1})])  # fmt: skip
    assert http_with(lambda r: next(answers)).request_json("GET", "https://brouter.example") == {"ok": 1}


def test_per_host_concurrency_limit_is_respected():
    import threading
    import time as _time
    from concurrent.futures import ThreadPoolExecutor

    active, peak, lock = [0], [0], threading.Lock()

    def handler(request):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        _time.sleep(0.05)
        with lock:
            active[0] -= 1
        return httpx.Response(200, json={"ok": 1})

    http = CachedHttp(
        None, transport=httpx.MockTransport(handler), sleep=lambda s: None, host_limits={"api.example": (2, 0)}
    )
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: http.request_json("GET", "https://api.example/x", params={"i": i}), range(8)))
    assert peak[0] <= 2


def test_retry_after_is_honoured_and_brouter_403_retried():
    slept = []
    answers = iter([httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200, json={"ok": 1})])
    http = CachedHttp(None, transport=httpx.MockTransport(lambda r: next(answers)), sleep=slept.append)
    assert http.request_json("GET", "https://data.geopf.fr/x") == {"ok": 1}
    assert 3.0 in slept

    answers2 = iter([httpx.Response(403, text="Forbidden"), httpx.Response(200, json={"ok": 2})])
    http2 = CachedHttp(None, transport=httpx.MockTransport(lambda r: next(answers2)), sleep=lambda s: None)
    assert http2.request_json("GET", "https://brouter.de/brouter") == {"ok": 2}
