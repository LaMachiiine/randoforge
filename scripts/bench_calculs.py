"""Mesure des calculs locaux (sans réseau) sur un itinéraire synthétique de 66 km densifié à 10 m.

Usage : uv run python scripts/bench_calculs.py
Résultats de référence : section « Performances » de docs/10 - Architecture/Architecture globale.md.
"""

from __future__ import annotations

import math
import time

import numpy as np

from randoforge.core import bivouac, stages
from randoforge.core.geo import densify
from randoforge.core.models import ElevationParams, Route, TrackPoint, WalkerProfile
from randoforge.core.osmgeom import RouteFrame
from randoforge.core.similarity import deviation, overlap_fraction
from randoforge.core.stats import compute_stats
from randoforge.core.terrain import retraced_sections, steep_sections
from randoforge.formats.gpx import write_gpx
from randoforge.formats.html import write_map
from randoforge.validation import validate


def timed(results: dict[str, float], name: str, f, rep: int = 3):
    t0 = time.perf_counter()
    for _ in range(rep):
        out = f()
    results[name] = (time.perf_counter() - t0) / rep * 1000
    return out


def main() -> None:
    t = np.linspace(0, 1, 2400)
    lats = 45 + 0.25 * t + 0.01 * np.sin(t * 60)
    lons = 6 + 0.25 * np.sin(t * 3) + 0.01 * np.cos(t * 50)
    res: dict[str, float] = {}
    dl, dn = timed(res, "densify", lambda: densify(lats, lons, 10.0))
    pts = [
        TrackPoint(lat=a, lon=b, ele=1000 + 400 * math.sin(i / 700) + 3 * math.sin(i / 7))
        for i, (a, b) in enumerate(zip(dl, dn, strict=True))
    ]
    other = [TrackPoint(lat=p.lat + 1.5e-4, lon=p.lon) for p in reversed(pts)]  # ~17 m à côté, sens inverse
    stats, _ = timed(res, "compute_stats", lambda: compute_stats(pts))
    timed(res, "retraced_sections", lambda: retraced_sections(pts))
    timed(res, "steep_sections", lambda: steep_sections(pts))
    timed(res, "RouteFrame", lambda: RouteFrame(pts))
    timed(res, "bivouac.probe_points", lambda: bivouac.probe_points(pts))
    cuts = [stages.Cut(m=m, label=str(m), kind="refuge gardé") for m in range(3000, 75000, 2500)]
    timed(res, "stages.plan", lambda: stages.plan(pts, ElevationParams(), WalkerProfile(), cuts, 4, None, [], []))
    timed(res, "overlap_fraction", lambda: overlap_fraction(pts, other))
    timed(res, "deviation", lambda: deviation(pts, other))
    route = Route(route_id="r_2026-10-16_abcdef", name="Banc d'essai", source="bench", points=pts, stats=stats)
    timed(res, "validate", lambda: validate(route))
    timed(res, "write_gpx", lambda: write_gpx(route))
    timed(res, "write_map", lambda: write_map(route))
    raw = timed(res, "stockage : écriture JSON", lambda: route.model_dump_json())
    timed(res, "stockage : lecture JSON", lambda: Route.model_validate_json(raw))
    print(f"{len(pts)} points, {stats.distance_km} km, JSON {len(raw) // 1024} Ko")
    for name, ms in sorted(res.items(), key=lambda kv: -kv[1]):
        print(f"  {name:26s} {ms:8.1f} ms")


if __name__ == "__main__":
    main()
