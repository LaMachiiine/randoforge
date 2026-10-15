"""Contenu commun à la fiche Markdown et au roadbook : chaque section = titre + tableau + notes."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.models import Route
from .gpx import POI_LABELS


@dataclass
class Section:
    title: str
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def highlights(route: Route) -> list[str]:
    top = sorted(route.pois or [], key=lambda p: -p.score)[:3]
    return [f"{p.nom or POI_LABELS.get(p.categorie, p.categorie)} (km {p.km:.1f})" for p in top if p.score >= 0.4]


def stages(route: Route) -> Section | None:
    if not route.stages:
        return None
    return Section(
        "Étapes",
        ["Jour", "km", "Distance", "D+ / D-", "Durée", "Arrivée", "Vigilance"],
        [
            [
                str(s.jour),
                f"{s.km_debut:.1f} → {s.km_fin:.1f}",
                f"{s.distance_km:.1f} km",
                f"{s.d_plus_m} / {s.d_minus_m} m",
                s.duree,
                f"{s.arrivee} ({s.arrivee_type})",
                "; ".join(s.passages_techniques + ([] if s.points_eau else ["pas d'eau connue"])),
            ]
            for s in route.stages
        ],
    )


def pois(route: Route) -> Section | None:
    if route.pois is None:
        return None
    if not route.pois:
        return Section(
            "À voir en chemin", notes=["Aucun point notable cartographié dans OpenStreetMap le long du tracé."]
        )
    rows = []
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
        if p.description:
            detail.append(p.description)
        rows.append([f"{p.km:.1f}", what, ", ".join(detail)])
    return Section("À voir en chemin", ["km", "Quoi", "Détail"], rows)


def technical(route: Route) -> Section | None:
    if route.technical is None:
        return None
    if not route.technical:
        return Section("Passages techniques", notes=["Aucun passage technique détecté."])
    rows = [
        [
            f"{t.km:.1f}",
            f"{t.longueur_m:.0f} m",
            t.niveau or "—",
            " ; ".join(t.details) + (" (à vérifier)" if t.a_verifier else ""),
        ]
        for t in route.technical
    ]
    return Section(
        "Passages techniques",
        ["km", "Longueur", "Niveau", "Quoi"],
        rows,
        ["Niveaux : échelle CAS T1 (sentier) à T6 (alpinisme), d'après OpenStreetMap."],
    )


def areas(route: Route) -> Section | None:
    if not route.areas:
        return None
    rows = [
        [
            f"{a.km_debut:.1f} → {a.km_fin:.1f}",
            f"{a.kind}{' — ' + a.nom if a.nom else ''}",
            a.chiens or "?",
            a.bivouac or "?",
        ]
        for a in route.areas
    ]
    notes = list(dict.fromkeys(n for a in route.areas for n in a.notes))
    return Section("Zones réglementées", ["km", "Zone", "Chiens", "Bivouac"], rows, notes)


def bivouacs(route: Route, limit: int = 12) -> Section | None:
    if not route.bivouacs:
        return None
    best = sorted(route.bivouacs, key=lambda b: -b.score)[:limit]
    rows = []
    for b in sorted(best, key=lambda b: b.km):
        detail = [
            f"{b.alt:.0f} m" if b.alt else "",
            f"eau à {b.eau_m:.0f} m" if b.eau_m is not None else "eau ?",
            f"pente {b.pente_pct:.0f} %" if b.pente_pct is not None else "",
            f"{b.places} places" if b.places else "",
        ]
        rows.append(
            [
                f"{b.km:.1f}",
                f"{b.type}{' — ' + b.nom if b.nom else ''}",
                b.source,
                ", ".join(x for x in detail if x),
                "; ".join(b.avertissements),
            ]
        )
    return Section("Où dormir", ["km", "Quoi", "Source", "Détail", "Avertissements"], rows)


def weather(route: Route) -> Section | None:
    w = route.weather
    if not w:
        return None
    rows = [
        [
            x.lieu,
            f"{x.altitude_m:.0f} m",
            f"{x.temp_min_c:.0f} à {x.temp_max_c:.0f} °C" if x.temp_min_c is not None else "?",
            f"{x.pluie_mm} mm" if x.pluie_mm is not None else "?",
            f"{x.rafales_max_kmh:.0f} km/h" if x.rafales_max_kmh is not None else "?",
            "oui" if x.orage else "non",
        ]
        for x in w.points
    ]
    return Section(
        f"Météo du {w.date:%d/%m/%Y} ({w.heures})",
        ["Lieu", "Altitude", "Températures", "Pluie", "Rafales", "Orage"],
        rows,
        w.alertes + [f"Source : {w.source}"],
    )


def validation(route: Route) -> Section | None:
    v = route.validation
    if not v:
        return None
    rows = [
        [
            c.id,
            c.level,
            f"{c.km:.1f}" if c.km is not None else "",
            c.message + (f" → {c.suggestion}" if c.suggestion else ""),
        ]
        for c in v.checks
        if c.level != "info"
    ]
    infos = [c.message for c in v.checks if c.level == "info"]
    return Section(f"Validation : {v.status}", ["Règle", "Niveau", "km", "Message"], rows, infos)


def quality(route: Route) -> Section | None:
    q = route.quality
    if not q:
        return None
    return Section(f"Confiance dans les données : {q.niveau} ({q.score:.2f})", notes=q.raisons)


def all_sections(route: Route) -> list[Section]:
    builders = (stages, pois, technical, areas, bivouacs, weather, validation, quality)
    return [s for b in builders if (s := b(route))]
