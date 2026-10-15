import numpy as np
import pytest

from randoforge.core.elevation import elevation_gain, median_smooth
from randoforge.core.geo import cumulative_distance, distance_m, resample
from randoforge.core.models import TrackPoint, WalkerProfile
from randoforge.core.stats import compute_stats
from randoforge.core.timing import estimate_minutes, format_duration

# --- Géodésie -----------------------------------------------------------------


def test_one_degree_latitude_at_equator():
    # Valeur de référence WGS84 : 110 574 m entre 0° et 1° de latitude.
    assert distance_m((0.0, 0.0), (1.0, 0.0)) == pytest.approx(110_574, rel=1e-4)


def test_cumulative_distance_is_additive():
    lats = np.array([45.0, 45.01, 45.02])
    lons = np.array([6.0, 6.0, 6.0])
    cum = cumulative_distance(lats, lons)
    assert cum[0] == 0
    assert cum[-1] == pytest.approx(distance_m((45.0, 6.0), (45.02, 6.0)), rel=1e-6)


def test_resample_keeps_endpoints_and_step():
    lats = np.array([45.0, 45.009])  # ~1 km vers le nord
    lons = np.array([6.0, 6.0])
    eles = np.array([1000.0, 1100.0])
    dist, rl, rlon, re = resample(lats, lons, eles, step_m=10)
    assert dist[-1] == pytest.approx(cumulative_distance(lats, lons)[-1])
    assert np.all(np.diff(dist)[:-1] == pytest.approx(10))
    assert (rl[0], rl[-1]) == (45.0, 45.009)
    assert (re[0], re[-1]) == (1000.0, 1100.0)


def test_resample_ignores_duplicate_points():
    lats = np.array([45.0, 45.0, 45.001])
    lons = np.array([6.0, 6.0, 6.0])
    eles = np.array([1.0, 1.0, 2.0])
    dist, *_ = resample(lats, lons, eles, step_m=10)
    assert np.all(np.diff(dist) > 0)


# --- Dénivelé -----------------------------------------------------------------


def test_gain_on_clean_climb():
    assert elevation_gain(np.linspace(0, 500, 501), 5) == (500, 0)


def test_gain_does_not_lose_threshold_at_summit():
    # Montée à 102 m puis retour à 0 : un seuil naïf donnerait 100/100.
    eles = np.concatenate([np.arange(0, 103), np.arange(101, -1, -1)]).astype(float)
    up, down = elevation_gain(eles, 5)
    assert (up, down) == (102, 102)


def test_gain_ignores_noise_below_threshold():
    x = np.arange(2000)
    eles = 1000 + 2.0 * np.sin(x)  # bruit ±2 m sur terrain plat
    assert elevation_gain(eles, 5) == (0, 0)


def test_noise_inflates_naive_gain_but_not_pipeline():
    x = np.linspace(0, 5000, 501)  # 5 km, un point tous les 10 m
    true = x * 0.1  # 500 m de montée régulière
    noisy = true + 3.0 * np.sin(x / 7)
    naive = np.sum(np.clip(np.diff(noisy), 0, None))
    up, _ = elevation_gain(median_smooth(noisy, 7), 5)
    assert naive > 600  # le calcul naïf surestime nettement
    assert up == pytest.approx(500, rel=0.02)


def test_median_smooth_removes_spike():
    eles = np.full(21, 100.0)
    eles[10] = 180.0
    assert median_smooth(eles, 5).max() == 100.0


# --- Durée --------------------------------------------------------------------


def test_din33466():
    # t_h = 2,5 h ; t_v = 1000/300 + 1000/500 = 5,333 h ; durée = 5,333 + 1,25 = 6,583 h
    assert estimate_minutes(10, 1000, 1000, WalkerProfile()) == 395
    assert format_duration(395) == "6h35"


# --- Statistiques complètes ---------------------------------------------------


def _out_and_back(n=200, top=300.0):
    up = [TrackPoint(lat=45.0 + i * 1e-4, lon=6.0, ele=1000 + top * i / n) for i in range(n + 1)]
    return up + up[-2::-1]


def test_stats_on_loop():
    stats, warnings = compute_stats(_out_and_back())
    assert stats.is_loop
    assert stats.distance_km == pytest.approx(4.45, abs=0.01)  # 2 × 200 × ~11,1 m
    assert stats.d_plus_m == stats.d_minus_m
    # Le filtre médian écrête légèrement un sommet en V (compromis documenté).
    assert stats.d_plus_m == pytest.approx(300, abs=3)
    assert stats.alt_min_m == 1000
    assert stats.alt_max_m == pytest.approx(1300, abs=3)
    assert stats.duration_label is not None
    assert warnings == []


def test_stats_without_elevation_warns_instead_of_guessing():
    pts = [TrackPoint(lat=45.0, lon=6.0), TrackPoint(lat=45.01, lon=6.0)]
    stats, warnings = compute_stats(pts)
    assert stats.d_plus_m is None and stats.duration_min is None
    assert "sans altitude" in warnings[0]


def test_stats_rejects_single_point():
    with pytest.raises(ValueError):
        compute_stats([TrackPoint(lat=45, lon=6, ele=1)])
