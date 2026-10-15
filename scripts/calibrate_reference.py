"""Calibration du dénivelé sur des références officielles (réseau requis).

    uv run python scripts/calibrate_reference.py [itinéraires_par_parc] [--report]

Trois mesures :
1. D+ publié par les parcs nationaux (Geotrek : Écrins, Cévennes) vs D+ RandoForge (MNT IGN) sur les mêmes tracés.
2. Même tracé avec les altitudes fournies par Geotrek, passé dans notre algorithme : isole l'effet de l'algorithme
   de celui du MNT.
3. Altitude officielle des sommets (tag `ele` OSM, issu des cartes IGN) vs MNT IGN au même point.
Puis une grille (lissage × seuil) pour vérifier que les réglages par défaut sont les bons.
`--report` écrit le résultat dans docs/10 - Architecture/Calibration du dénivelé.md.
"""

from __future__ import annotations

import logging
import statistics
import sys
import tempfile
from datetime import date
from pathlib import Path

from randoforge.app import App
from randoforge.core.models import ElevationParams, Route, TrackPoint
from randoforge.core.stats import compute_stats
from randoforge.engines.geotrek import GeotrekReference
from randoforge.http import CachedHttp
from randoforge.services import Services
from randoforge.storage import RouteStore, default_home

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "10 - Architecture" / "Calibration du dénivelé.md"
PEAK_AREAS = {"ecrins": (44.75, 6.1, 45.05, 6.5), "cevennes": (44.15, 3.5, 44.45, 3.9)}
GRID_SMOOTH = [0, 30, 60, 100]
GRID_THRESHOLD = [0, 2, 3, 5, 8]


def pct(a: float, b: float) -> float:
    return 100 * (a - b) / b


def summary(errors: list[float]) -> tuple[float, float, float]:
    """(médiane des écarts absolus, biais médian, part des itinéraires à moins de 10 %)."""
    abs_e = [abs(e) for e in errors]
    return statistics.median(abs_e), statistics.median(errors), 100 * sum(e <= 10 for e in abs_e) / len(abs_e)


def main(per_park: int, write_report: bool) -> None:
    home = default_home()
    app = App(RouteStore(Path(tempfile.mkdtemp())), Services.from_env(home))
    ref = GeotrekReference(CachedHttp(home / "cache.sqlite"))
    rows, grid_points = [], []
    for park in ("ecrins", "cevennes"):
        for t in ref.treks(park, per_park):
            route = Route(route_id="r_2000-01-01_000000", name=t.name, source=f"geotrek:{park}",
                          points=[TrackPoint(lat=la, lon=lo) for la, lo, _ in t.coords])  # fmt: skip
            app.apply_dem(route)
            ours, _ = compute_stats(route.points)
            theirs_z = [TrackPoint(lat=la, lon=lo, ele=z) for la, lo, z in t.coords]
            algo_only = compute_stats(theirs_z)[0] if all(z is not None for *_, z in t.coords) else None
            rows.append((park, t, ours, algo_only))
            grid_points.append((park, route.points, t.ascent_m))
            print(
                f"{park:9} {t.name[:38]:38} {t.length_km:5.1f} km  D+ publié {t.ascent_m:5}  RandoForge {ours.d_plus_m:5}"
                f"  ({pct(ours.d_plus_m, t.ascent_m):+5.1f} %)  algo seul {algo_only.d_plus_m if algo_only else '?':>5}"
            )

    dplus = [pct(o.d_plus_m, t.ascent_m) for _, t, o, _ in rows]
    algo = [pct(a.d_plus_m, t.ascent_m) for _, t, _, a in rows if a]
    dist = [pct(o.distance_km, t.length_km) for _, t, o, _ in rows]
    by_park = {
        p: summary([pct(o.d_plus_m, t.ascent_m) for q, t, o, _ in rows if q == p]) for p in ("ecrins", "cevennes")
    }

    print("\nGrille lissage × seuil (médiane des écarts absolus de D+, %) :")
    grid = {}
    for sm in GRID_SMOOTH:
        for th in GRID_THRESHOLD:
            params = ElevationParams(smooth_window_m=sm, threshold_m=th)
            errs = [abs(pct(compute_stats(pts, params)[0].d_plus_m, asc)) for _, pts, asc in grid_points]
            grid[(sm, th)] = statistics.median(errs)
        print(f"  lissage {sm:3} m : " + "  ".join(f"seuil {th} m → {grid[(sm, th)]:4.1f}" for th in GRID_THRESHOLD))
    best = min(grid, key=grid.get)

    def per_park(sm: int, th: int) -> str:
        params = ElevationParams(smooth_window_m=sm, threshold_m=th)
        parts = []
        for park in ("ecrins", "cevennes"):
            errs = [pct(compute_stats(pts, params)[0].d_plus_m, asc) for q, pts, asc in grid_points if q == park]
            m, b, _ = summary(errs)
            parts.append(f"{park} {m:.1f} % (biais {b:+.1f} %)")
        return " · ".join(parts)

    per_park_lines = [f"| {sm} m / {th} m | {per_park(sm, th)} |" for sm, th in dict.fromkeys([(30, 5), best])]

    peaks = []
    for park, (s, w, n, e) in PEAK_AREAS.items():
        els = app.overpass(f'[out:json][timeout:60];node["natural"="peak"]["ele"]["name"]({s},{w},{n},{e});out 40;')
        pts, eles = [], []
        for el in els:
            try:
                eles.append(float(el["tags"]["ele"].replace(",", ".")))
                pts.append((el["lat"], el["lon"]))
            except ValueError:
                continue
        dem = app.elevations(pts).values
        peaks += [(park, d - e) for d, e in zip(dem, eles, strict=True) if d is not None]

    med, bias, within = summary(dplus)
    lines = [
        "---", "tags: [architecture, calibration]", f"maj: {date.today().isoformat()}", "---",
        "# Calibration du dénivelé", "",
        "> Généré par `scripts/calibrate_reference.py`. Références officielles : itinéraires publiés par les parcs "
        "nationaux des Écrins et des Cévennes (plateforme Geotrek) et altitudes officielles des sommets.", "",
        "## Résultats", "",
        "| Mesure | Médiane des écarts absolus | Biais médian | À moins de 10 % |", "|---|---|---|---|",
        f"| D+ RandoForge vs D+ publié ({len(dplus)} itinéraires) | {med:.1f} % | {bias:+.1f} % | {within:.0f} % |",
        *[f"| … dont {p} | {m:.1f} % | {b:+.1f} % | {w:.0f} % |" for p, (m, b, w) in by_park.items()],
        f"| Même tracé, altitudes Geotrek, notre algorithme | {summary(algo)[0]:.1f} % | {summary(algo)[1]:+.1f} % | {summary(algo)[2]:.0f} % |",
        f"| Distance RandoForge vs distance publiée | {statistics.median(abs(d) for d in dist):.1f} % | {statistics.median(dist):+.1f} % | — |",
        *[f"| Altitude MNT au sommet vs altitude officielle — {p} ({len(e)} sommets) | {statistics.median(abs(d) for d in e):.1f} m | "
           f"{statistics.median(e):+.1f} m | — |" for p, e in ((p, [d for q, d in peaks if q == p]) for p in PEAK_AREAS) if e],
        "", "## Grille lissage × seuil (médiane des écarts absolus de D+)", "",
        "| Lissage \\ seuil | " + " | ".join(f"{t} m" for t in GRID_THRESHOLD) + " |", "|---|" + "---|" * len(GRID_THRESHOLD),
        *[f"| {sm} m | " + " | ".join(f"{grid[(sm, th)]:.1f} %" for th in GRID_THRESHOLD) + " |" for sm in GRID_SMOOTH],
        "", "### Par parc (le réglage global optimal peut favoriser un parc au détriment de l'autre)", "",
        "| Réglage (lissage / seuil) | Écart médian par parc |", "|---|---|", *per_park_lines,
        "", f"Meilleur réglage sur cet échantillon : lissage {best[0]} m, seuil {best[1]} m "
        f"({grid[best]:.1f} %) ; réglage par défaut (30 m, 5 m) : {grid[(30, 5)]:.1f} %.", "",
        "## Itinéraires", "", "| Parc | Itinéraire | km | D+ publié | D+ RandoForge | Écart | D+ algo seul |", "|---|---|---|---|---|---|---|",
        *[f"| {p} | {t.name} | {t.length_km:.1f} | {t.ascent_m} | {o.d_plus_m} | {pct(o.d_plus_m, t.ascent_m):+.1f} % | "
          f"{a.d_plus_m if a else '?'} |" for p, t, o, a in rows],
        "", "Données : © Parc national des Écrins, © Parc national des Cévennes (Geotrek), © contributeurs OpenStreetMap, IGN.", "",
    ]  # fmt: skip
    print("\n".join(lines[8:16]))
    if write_report:
        REPORT.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nRapport écrit : {REPORT}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(int(args[0]) if args else 25, "--report" in sys.argv)
