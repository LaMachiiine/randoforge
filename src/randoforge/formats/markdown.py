"""Fiche rando au format Markdown, compatible Obsidian/Dataview."""

from __future__ import annotations

from ..core.models import Route
from .gpx import ATTRIBUTION


def write_fiche(route: Route, gpx_filename: str = "route.gpx") -> str:
    s = route.stats

    def fm(value: object) -> str:
        return "" if value is None else str(value)

    frontmatter = {
        "tags": "[rando]",
        "route_id": route.route_id,
        "date_creation": route.created_at.date().isoformat(),
        "type": "boucle" if s and s.is_loop else "aller simple",
        "distance_km": fm(s and s.distance_km),
        "d_plus": fm(s and s.d_plus_m),
        "d_minus": fm(s and s.d_minus_m),
        "alt_min": fm(s and s.alt_min_m),
        "alt_max": fm(s and s.alt_max_m),
        "duree": fm(s and s.duration_label),
        "gpx": gpx_filename,
    }
    lines = ["---", *(f"{k}: {v}" for k, v in frontmatter.items()), "---", f"# {route.name}", ""]

    if s:
        dplus = f"{s.d_plus_m} m D+" if s.d_plus_m is not None else "D+ inconnu"
        duree = s.duration_label or "durée inconnue"
        lines += ["> [!summary] En bref", f"> **{s.distance_km} km** · **{dplus}** · **{duree}**", ""]

    if route.warnings:
        lines += ["## Points de vigilance", "> [!warning]"]
        lines += [f"> - {w}" for w in route.warnings]
        lines.append("")

    lines += ["## Données", f"- Tracé : [[{gpx_filename}]]", f"- Source : {route.source}"]
    if s:
        p = s.params
        lines.append(
            f"- Calcul : altitudes {s.elevation_source}, pas {p.step_m:g} m, "
            f"lissage {p.smooth_window_m:g} m, seuil {p.threshold_m:g} m"
        )
        lines.append("- Durée : méthode DIN 33466, pauses non comprises")
    lines += [f"- {ATTRIBUTION}", ""]
    return "\n".join(lines)
