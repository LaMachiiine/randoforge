"""Fiche rando au format Markdown, compatible Obsidian/Dataview."""

from __future__ import annotations

from ..core.models import Route
from ..core.terrain import retraced_sections
from .gpx import ATTRIBUTION
from .sections import all_sections, highlights


def route_kind(route: Route) -> str:
    """« boucle », « aller-retour » (départ = arrivée, surtout sur le même chemin) ou « aller simple »."""
    s = route.stats
    if not (s and s.is_loop):
        return "aller simple"
    retraced = sum(sec.value for sec in retraced_sections(route.points)) / 1000
    return "aller-retour" if s.distance_km and retraced >= 0.4 * s.distance_km else "boucle"


def _t(text: object) -> str:
    """Texte venu d'OSM, Wikidata… : Obsidian rend le HTML inline, on neutralise les balises."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cell(text: str) -> str:
    return _t(text).replace("|", "\\|").replace("\n", " ")


def write_fiche(route: Route, gpx_filename: str = "route.gpx") -> str:
    s = route.stats

    def fm(value: object) -> str:
        return "" if value is None else str(value)

    frontmatter = {
        "tags": "[rando]",
        "route_id": route.route_id,
        "date_creation": route.created_at.date().isoformat(),
        "type": route_kind(route),
        "distance_km": fm(s and s.distance_km),
        "d_plus": fm(s and s.d_plus_m),
        "d_minus": fm(s and s.d_minus_m),
        "alt_min": fm(s and s.alt_min_m),
        "alt_max": fm(s and s.alt_max_m),
        "duree": fm(s and s.duration_label),
        "jours": len(route.stages) if route.stages else 1,
        "niveau_technique": max((t.niveau for t in route.technical or [] if t.niveau), default=""),
        "validation": route.validation.status if route.validation else "",
        "confiance": route.quality.niveau if route.quality else "",
        "fait_le": fm(route.done_on),
        "gpx": gpx_filename,
    }
    lines = ["---", *(f"{k}: {v}" for k, v in frontmatter.items()), "---", f"# {_t(route.name)}", ""]

    if s:
        dplus = f"{s.d_plus_m} m D+" if s.d_plus_m is not None else "D+ inconnu"
        if s.d_plus_fourchette_m:
            dplus += f" (plausible {s.d_plus_fourchette_m[0]}–{s.d_plus_fourchette_m[1]} m)"
        duree = s.duration_label or "durée inconnue"
        days = f" · **{len(route.stages)} jours**" if route.stages else ""
        lines += ["> [!summary] En bref", f"> **{s.distance_km} km** · **{dplus}** · **{duree}**{days}", ""]
    if best := highlights(route):
        lines += ["**À ne pas manquer :** " + " · ".join(f"⭐ {_t(h)}" for h in best), ""]
    if route.done_on:
        lines += [
            f"> [!done] Faite le {route.done_on:%d/%m/%Y}" + (f" — {route.done_notes}" if route.done_notes else ""),
            "",
        ]

    for sec in all_sections(route):
        lines += [f"## {sec.title}", ""]
        if sec.rows:
            lines += ["| " + " | ".join(sec.headers) + " |", "|" + "---|" * len(sec.headers)]
            lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in sec.rows]
            lines.append("")
        lines += [f"- {_t(n)}" for n in sec.notes]
        if sec.notes:
            lines.append("")

    if route.warnings:
        lines += ["## Points de vigilance", "> [!warning]"]
        lines += [f"> - {_t(w)}" for w in route.warnings]
        lines.append("")

    lines += ["## Données", f"- Tracé : [[{gpx_filename}]]", f"- Source : {route.source}"]
    if s:
        p = s.params
        lines.append(
            f"- Calcul : altitudes {s.elevation_source}, pas {p.step_m:g} m, "
            f"lissage {p.smooth_window_m:g} m, seuil {p.threshold_m:g} m"
        )
        lines.append("- Durée : méthode DIN 33466, pauses non comprises")
    lines += [f"- {ATTRIBUTION}", "- Refuges : © contributeurs refuges.info (CC BY-SA)", "- Carte : [[carte.html]]", ""]
    return "\n".join(lines)
