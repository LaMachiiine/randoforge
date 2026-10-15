"""Qualité des données d'un itinéraire et score de confiance.

- présence sur un chemin cartographié (essentiel pour une trace importée, règle G1) ;
- ancienneté médiane des chemins OSM empruntés (règle Q3) ;
- précision de l'altimétrie et renseignement de la difficulté.
"""

from __future__ import annotations

from datetime import UTC, datetime
from statistics import median

import numpy as np
import shapely

from .models import Quality, Route, WaySegment
from .osmgeom import RouteFrame, element_geometry
from .terrain import _runs

ON_PATH_M = 15.0
NOT_FOR_FEET = {"motorway", "motorway_link", "trunk_link", "construction", "proposed", "raceway", "bus_guideway"}


def build_query(frame: RouteFrame) -> str:
    return f'[out:json][timeout:120];way({frame.polyline_filter(ON_PATH_M + 10)})["highway"];out meta geom;'


def on_path(frame: RouteFrame, elements: list[dict]) -> tuple[float, list[tuple[float, float]]]:
    """(% de la longueur sur un chemin praticable, portions hors chemin en km)."""
    geoms = [
        g
        for el in elements
        if el.get("tags", {}).get("highway") not in NOT_FOR_FEET
        and el.get("tags", {}).get("foot") not in {"no", "private"}
        and (g := element_geometry(el, frame.proj)) is not None
    ]
    if not geoms:
        return 0.0, [(0.0, round(frame.cum[-1] / 1000, 2))]
    near = shapely.distance(shapely.union_all(geoms), frame.pts) <= ON_PATH_M
    seg = np.diff(frame.cum)
    pct = float(100 * seg[near[:-1] & near[1:]].sum() / seg.sum()) if seg.sum() else 100.0
    off = [
        (round(frame.cum[a] / 1000, 2), round(frame.cum[b] / 1000, 2))
        for a, b in _runs(~near)
        if frame.cum[b] - frame.cum[a] >= 30
    ]
    return round(pct, 1), off


def median_edit_year(elements: list[dict]) -> int | None:
    years = [int(el["timestamp"][:4]) for el in elements if el.get("timestamp")]
    return int(median(years)) if years else None


def marked_share(segments: list[WaySegment]) -> float | None:
    """Part du parcours sur des sentiers balisés (relations OSM de randonnée, d'après le moteur)."""
    if not segments:
        return None
    total = segments[-1].end_m or 1
    marked = sum(s.end_m - s.start_m for s in segments if any(k.startswith("route_hiking_") for k in s.tags))
    return round(100 * marked / total, 1)


def assess(route: Route, on_path_pct: float | None, off: list, edit_year: int | None) -> Quality:
    score, reasons = 1.0, []
    src = route.elevation_source
    if "IGN" in src or "MNT local" in src:
        reasons.append(f"Altitudes précises ({src}).")
    elif "Copernicus" in src:
        score -= 0.15
        reasons.append("Altitudes Copernicus 30 m (modèle de surface) : D+ moins précis.")
    elif "fichier" in src:
        score -= 0.1
        reasons.append("Altitudes issues du fichier GPX (précision inconnue).")
    if route.segments:
        paths = [s for s in route.segments if s.tags.get("highway") == "path"]
        path_len = sum(s.end_m - s.start_m for s in paths)
        missing = sum(s.end_m - s.start_m for s in paths if "sac_scale" not in s.tags)
        if path_len and missing / path_len > 0.5:
            score -= 0.15
            reasons.append(f"Difficulté non renseignée sur {100 * missing / path_len:.0f} % des sentiers.")
    else:
        reasons.append("Trace importée : chemins et difficulté déduits a posteriori.")
    if on_path_pct is not None and on_path_pct < 95:
        score -= 0.25
        reasons.append(f"Seulement {on_path_pct:.0f} % du tracé sur un chemin cartographié.")
    if edit_year and datetime.now(UTC).year - edit_year > 6:
        score -= 0.1
        reasons.append(f"Chemins peu mis à jour dans OSM (édition médiane {edit_year}).")
    if route.stats and route.stats.d_plus_m is None:
        score -= 0.3
        reasons.append("Dénivelé inconnu.")
    score = round(max(0.0, min(1.0, score)), 2)
    level = "haute" if score >= 0.8 else "moyenne" if score >= 0.55 else "faible"
    return Quality(
        score=score,
        niveau=level,
        raisons=reasons,
        sur_chemin_pct=on_path_pct,
        hors_chemin=off,
        annee_mediane_edition=edit_year,
    )
