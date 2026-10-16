"""Roadbook imprimable (HTML + CSS d'impression) : Ctrl+P → « Enregistrer au format PDF »."""

from __future__ import annotations

import html

from ..core.models import Route
from .gpx import ATTRIBUTION
from .html import _profile_svg
from .sections import all_sections, highlights, key_facts


def _e(text: object) -> str:
    return html.escape(str(text))


def write_roadbook(route: Route) -> str:
    facts = key_facts(route)
    body = [f"<h1>{_e(route.name)}</h1>"]
    body.append(
        '<dl class="facts">' + "".join(f"<div><dt>{_e(k)}</dt><dd>{_e(v)}</dd></div>" for k, v in facts) + "</dl>"
    )
    if best := highlights(route):
        body.append("<p><b>À ne pas manquer :</b> " + " · ".join(_e(h) for h in best) + "</p>")
    body.append(f'<section class="profile">{_profile_svg(route)}</section>')
    for sec in all_sections(route):
        part = [f"<section><h2>{_e(sec.title)}</h2>"]
        if sec.rows:
            part.append(
                "<table><thead><tr>" + "".join(f"<th>{_e(h)}</th>" for h in sec.headers) + "</tr></thead><tbody>"
            )
            part += ["<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>" for row in sec.rows]
            part.append("</tbody></table>")
        if sec.notes:
            part.append("<ul>" + "".join(f"<li>{_e(n)}</li>" for n in sec.notes) + "</ul>")
        part.append("</section>")
        body.append("".join(part))
    if route.warnings:
        body.append(
            "<section><h2>Points de vigilance</h2><ul>"
            + "".join(f"<li>{_e(w)}</li>" for w in route.warnings)
            + "</ul></section>"
        )
    body.append(
        f"<footer>{_e(ATTRIBUTION)} Refuges © refuges.info (CC BY-SA). Aide à la préparation : vérifier les "
        "conditions sur place.</footer>"
    )
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Roadbook — {_e(route.name)}</title>
<style>
:root {{ --fg:#1d2321; --muted:#5d6865; --line:#c2410c; --area:#fed7aa; --tech:#dc262633; --rule:#d9dedc; }}
body {{ margin:0 auto; max-width:900px; padding:16px; font:13px/1.45 system-ui, sans-serif; color:var(--fg); background:#fff; }}
h1 {{ font-size:22px; margin:0 0 8px; }} h2 {{ font-size:15px; margin:18px 0 6px; border-bottom:2px solid var(--line); }}
.facts {{ display:flex; flex-wrap:wrap; gap:8px 20px; margin:0 0 8px; }} .facts dt {{ color:var(--muted); font-size:11px; }}
.facts dd {{ margin:0; font-weight:600; }}
table {{ width:100%; border-collapse:collapse; }} th, td {{ text-align:left; padding:3px 6px; border-bottom:1px solid var(--rule); vertical-align:top; }}
th {{ font-size:11px; color:var(--muted); }} section {{ break-inside:avoid; }}
.profile svg {{ width:100%; height:auto; }} .profile text {{ fill:var(--muted); font-size:11px; }}
.profile .line {{ fill:none; stroke:var(--line); stroke-width:2; }} .profile .area {{ fill:var(--area); }} .profile .tech {{ fill:var(--tech); }}
footer {{ margin-top:20px; color:var(--muted); font-size:11px; }}
@media print {{ body {{ padding:0; }} @page {{ margin:12mm; }} }}
</style></head><body>
{"".join(body)}
</body></html>
"""
