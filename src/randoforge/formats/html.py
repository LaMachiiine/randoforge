"""Carte HTML autonome : fond topographique, tracé, points notables, passages techniques, profil altimétrique."""

from __future__ import annotations

import html
import json

import numpy as np

from ..core.geo import cumulative_distance
from ..core.models import Route
from .gpx import POI_LABELS
from .sections import key_facts

LEAFLET = "https://unpkg.com/leaflet@1.9.4/dist"
PROFILE_W, PROFILE_H, PAD = 900, 200, 36


def _profile_svg(route: Route) -> str:
    if not route.points or any(p.ele is None for p in route.points):
        return "<p>Profil indisponible : altitudes manquantes.</p>"
    lats = np.array([p.lat for p in route.points])
    lons = np.array([p.lon for p in route.points])
    km = cumulative_distance(lats, lons) / 1000
    ele = np.array([p.ele for p in route.points], dtype=float)
    lo, hi = float(ele.min()), float(ele.max())
    span = max(hi - lo, 50.0)
    lo -= span * 0.05
    hi = lo + span * 1.1

    def x(k: float) -> float:
        return PAD + (PROFILE_W - 2 * PAD) * k / max(km[-1], 1e-9)

    def y(e: float) -> float:
        return PROFILE_H - PAD + (PAD * 2 - PROFILE_H) * (e - lo) / (hi - lo)

    step = max(1, len(km) // 600)
    pts = " ".join(f"{x(k):.1f},{y(e):.1f}" for k, e in zip(km[::step], ele[::step], strict=True))
    base = f"{x(0):.1f},{PROFILE_H - PAD} {pts} {x(km[-1]):.1f},{PROFILE_H - PAD}"
    bands = "".join(
        f'<rect class="tech" x="{x(t.km):.1f}" y="{PAD / 2}" width="{max(2.0, x(t.km + t.longueur_m / 1000) - x(t.km)):.1f}" '
        f'height="{PROFILE_H - 1.5 * PAD}"><title>km {t.km:.1f} : {html.escape(", ".join(t.types))}</title></rect>'
        for t in route.technical or []
    )
    ticks = "".join(
        f'<text x="{x(k):.1f}" y="{PROFILE_H - PAD + 16}" text-anchor="middle">{k:g}</text>'
        for k in np.arange(0, km[-1] + 1e-9, max(1, round(km[-1] / 10)))
    )
    alts = "".join(
        f'<text x="{PAD - 6}" y="{y(e) + 4:.1f}" text-anchor="end">{e:.0f}</text>' for e in (ele.min(), ele.max())
    )
    return (
        f'<svg viewBox="0 0 {PROFILE_W} {PROFILE_H}" role="img" aria-label="Profil altimétrique">'
        f'{bands}<polygon class="area" points="{base}"/><polyline class="line" points="{pts}"/>'
        f'{ticks}{alts}<text x="{PROFILE_W - PAD}" y="{PROFILE_H - 4}" text-anchor="end">km</text></svg>'
    )


def write_map(route: Route) -> str:
    coords = [[p.lat, p.lon] for p in route.points]
    pois = [
        {
            "lat": p.lat,
            "lon": p.lon,
            "label": (p.nom or POI_LABELS.get(p.categorie, p.categorie)) + (f" ({p.via})" if p.via else ""),
            "km": p.km,
            "cat": p.categorie,
        }
        for p in route.pois or []
        if p.nom or p.score >= 0.3 or p.via
    ]
    lats = np.array([p.lat for p in route.points])
    lons = np.array([p.lon for p in route.points])
    cum = cumulative_distance(lats, lons)
    tech = []
    for t in route.technical or []:
        i0, i1 = np.searchsorted(cum, [t.km * 1000, t.km * 1000 + t.longueur_m])
        seg = coords[int(i0) : max(int(i1), int(i0) + 2)]
        tech.append({"coords": seg, "label": f"km {t.km:.1f} — " + " ; ".join(t.details)})

    summary = " · ".join(
        f"{html.escape(k)} : <b>{html.escape(v)}</b>" for k, v in key_facts(route) if k != "Validation"
    )
    status = route.validation.status if route.validation else "non validé"
    title = html.escape(route.name)
    # Les noms viennent d'OSM (modifiables par tous) : on empêche toute sortie du bloc <script>.
    nights = [
        {
            "lat": float(np.interp(st.km_fin * 1000, cum, lats)),
            "lon": float(np.interp(st.km_fin * 1000, cum, lons)),
            "label": f"Nuit {st.jour} : {st.arrivee}",
        }
        for st in (route.stages or [])[:-1]
    ]
    camps = [
        {"lat": b.lat, "lon": b.lon, "label": f"{b.type}{' — ' + b.nom if b.nom else ''} (km {b.km:.1f}, {b.source})"}
        for b in sorted(route.bivouacs or [], key=lambda b: -b.score)[:15]
    ]
    payload = {"coords": coords, "pois": pois, "tech": tech, "nights": nights, "camps": camps}
    # Tout « < » est encodé : ni « </script> » ni « <!-- » ne peuvent perturber l'analyse du bloc <script>.
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{LEAFLET}/leaflet.css">
<style>
:root {{ --bg:#fff; --fg:#1d2321; --muted:#5d6865; --line:#c2410c; --area:#fed7aa; --tech:#dc262633; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141816; --fg:#e7ece9; --muted:#9aa5a1; --area:#7c2d1288; }} }}
body {{ margin:0; font:15px/1.45 system-ui, sans-serif; background:var(--bg); color:var(--fg); }}
header {{ padding:12px 16px; }} h1 {{ margin:0 0 4px; font-size:20px; }}
.meta {{ color:var(--muted); }} #map {{ height:62vh; }}
/* Styles limités au profil : un sélecteur « svg » global écraserait le SVG du tracé Leaflet. */
.profile {{ padding:8px 16px 16px; }} .profile svg {{ width:100%; height:auto; }}
.profile text {{ fill:var(--muted); font-size:11px; }} .profile .line {{ fill:none; stroke:var(--line); stroke-width:2; }}
.profile .area {{ fill:var(--area); }} .profile .tech {{ fill:var(--tech); }}
</style></head><body>
<header><h1>{title}</h1><div>{summary}</div>
<div class="meta">Validation : {html.escape(status)} · rouge = passage technique · violet = où dormir · © OpenStreetMap, OpenTopoMap, IGN</div></header>
<div id="map"></div>
<div class="profile">{_profile_svg(route)}</div>
<script src="{LEAFLET}/leaflet.js"></script>
<script>
const d = {data};
const esc = s => String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const map = L.map('map');
const bounds = L.latLngBounds(d.coords);
// La vue doit exister avant d'ajouter les couches vectorielles, sinon elles sont dessinées à une échelle périmée.
map.fitBounds(bounds, {{padding: [20, 20], animate: false}});
L.tileLayer('https://{{s}}.tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 17, attribution: '© OpenStreetMap, SRTM | style © OpenTopoMap (CC-BY-SA)' }}).addTo(map);
const line = L.polyline(d.coords, {{color: '#c2410c', weight: 4}}).addTo(map);
d.tech.forEach(t => L.polyline(t.coords, {{color: '#dc2626', weight: 8, opacity: .7}}).bindPopup(esc(t.label)).addTo(map));
d.pois.forEach(p => L.circleMarker([p.lat, p.lon], {{radius: 6, color: p.cat === 'riviere' ? '#2563eb' : '#15803d'}})
  .bindPopup(`<b>${{esc(p.label)}}</b><br>km ${{p.km.toFixed(1)}}`).addTo(map));
L.marker(d.coords[0]).bindPopup('Départ').addTo(map);
d.camps.forEach(c => L.circleMarker([c.lat, c.lon], {{radius: 5, color: '#7c3aed', dashArray: '3'}}).bindPopup(esc(c.label)).addTo(map));
d.nights.forEach(n => L.marker([n.lat, n.lon]).bindPopup(`<b>${{esc(n.label)}}</b>`).addTo(map));
// Recadre quand la taille du conteneur change (panneau redimensionné), tant que l'utilisateur n'a pas bougé la carte.
let userMoved = false;
map.on('dragstart', () => {{ userMoved = true; }});
map.getContainer().addEventListener('wheel', () => {{ userMoved = true; }}, {{passive: true}});
new ResizeObserver(() => {{
  map.invalidateSize({{animate: false}});
  if (!userMoved) map.fitBounds(bounds, {{padding: [20, 20], animate: false}});}}).observe(map.getContainer());
</script></body></html>
"""
