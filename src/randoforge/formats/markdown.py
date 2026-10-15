"""Fiche rando au format Markdown, compatible Obsidian/Dataview."""

from __future__ import annotations

from ..core.models import Route
from .gpx import ATTRIBUTION, POI_LABELS


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
        "validation": route.validation.status if route.validation else "",
        "gpx": gpx_filename,
    }
    lines = ["---", *(f"{k}: {v}" for k, v in frontmatter.items()), "---", f"# {route.name}", ""]

    if s:
        dplus = f"{s.d_plus_m} m D+" if s.d_plus_m is not None else "D+ inconnu"
        duree = s.duration_label or "durée inconnue"
        lines += ["> [!summary] En bref", f"> **{s.distance_km} km** · **{dplus}** · **{duree}**", ""]

    if route.pois:
        top = sorted(route.pois, key=lambda p: -p.score)[:3]
        lines += ["## À voir en chemin", ""]
        lines += [
            f"- ⭐ **{p.nom or POI_LABELS.get(p.categorie, p.categorie)}** (km {p.km:.1f})"
            for p in top
            if p.score >= 0.4
        ]
        lines += ["", "| km | Quoi | Détail |", "|---|---|---|"]
        for p in route.pois:
            what = POI_LABELS.get(p.categorie, p.categorie) + (f" — {p.nom}" if p.nom else "")
            detail = []
            if p.via:
                detail.append(f"⚠️ {p.via}")
            if p.detour_m:
                detail.append(f"détour ~{p.detour_m:.0f} m")
            if p.ele:
                detail.append(f"{p.ele:.0f} m")
            if p.intermittent:
                detail.append("peut être à sec")
            lines.append(f"| {p.km:.1f} | {what} | {', '.join(detail)} |")
        lines.append("")
    elif route.pois == []:
        lines += [
            "## À voir en chemin",
            "Aucun point notable cartographié dans OpenStreetMap le long du tracé.",
            "",
        ]

    if route.validation:
        v = route.validation
        lines += [f"## Validation : {v.status}", ""]
        for c in v.checks:
            if c.level != "info":
                where = f"km {c.km:.1f} — " if c.km is not None else ""
                lines.append(f"- **{c.id}** ({c.level}) {where}{c.message}")
        lines.append("")

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
