"""Contenu commun à la fiche Markdown et au roadbook : chaque section = titre + tableau + notes."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.bivouac import useful_for_night
from ..core.models import Route
from .gpx import POI_LABELS


@dataclass
class Section:
    title: str
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _v(value: object, unit: str = "") -> str:
    return "inconnu" if value is None else f"{value}{unit}"


def key_facts(route: Route) -> list[tuple[str, str]]:
    """Chiffres clés communs à la carte et au roadbook (la fiche Markdown a les mêmes, en frontmatter)."""
    s = route.stats
    facts: list[tuple[str, str]] = []
    if s:
        facts = [
            ("Distance", f"{s.distance_km} km"),
            ("D+ / D-", f"{_v(s.d_plus_m)} / {_v(s.d_minus_m, ' m')}"),
            *(
                [("D+ plausible", f"{s.d_plus_fourchette_m[0]}–{s.d_plus_fourchette_m[1]} m")]
                if s.d_plus_fourchette_m
                else []
            ),  # fmt: skip
            ("Durée", f"{s.duration_label} (pauses non comprises)" if s.duration_label else "inconnue"),
            ("Altitudes", f"{s.alt_min_m}–{s.alt_max_m} m" if s.alt_min_m is not None else "inconnues"),
        ]
    if route.stages:
        facts.append(("Jours", str(len(route.stages))))
    facts.append(("Validation", route.validation.status if route.validation else "non validé"))
    if route.done_on:
        facts.append(("Faite le", f"{route.done_on:%d/%m/%Y}"))
    return facts


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
    total_km = route.stats.distance_km if route.stats else max((b.km for b in route.bivouacs or []), default=0)
    logical = useful_for_night(route.bivouacs or [], total_km, route.stages)
    if not logical:
        return None
    best = sorted(logical, key=lambda b: -b.score)[:limit]
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
                f"{b.type}{' — ' + b.nom if b.nom else ''}{' (abrité)' if b.abrite else ''}",
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


def snow(route: Route) -> Section | None:
    r = route.snow
    if not r or not r.applicable:
        return None
    rows = [[t] for t in r.troncons_enneiges]
    notes = [r.message]
    if r.limite_neige_m is not None:
        notes.append(f"Limite de la neige : ~{r.limite_neige_m} m ({r.limite_source})")
    elif r.limite_source:
        notes.append(r.limite_source)
    if r.epaisseur_modele_cm:
        notes.append(f"Épaisseur estimée (modèle) : {r.epaisseur_modele_cm[0]} à {r.epaisseur_modele_cm[1]} cm"
                     + (f", dont ~{r.neige_fraiche_72h_cm:g} cm tombés en 3 jours" if r.neige_fraiche_72h_cm else ""))  # fmt: skip
    if r.duree_neige and r.duree_neige != r.duree_normale:
        notes.append(f"Durée ajustée à la neige : ≈ {r.duree_neige} (au lieu de {r.duree_normale})"
                     + (", en raquettes" if r.en_raquettes else ""))  # fmt: skip
    notes += r.avertissements + [f"Sources : {', '.join(r.sources)}"]
    return Section(f"Neige ({r.date:%d/%m/%Y})", ["Tronçons enneigés"] if rows else [], rows, notes)


def avalanche(route: Route) -> Section | None:
    r = route.avalanche
    if not r:
        return None
    return Section("Terrain avalancheux (relief)", ["Tronçons exposés"] if r.troncons else [],
                   [[t] for t in r.troncons], [r.message, *r.avertissements, f"Source : {r.source}"])  # fmt: skip


def water(route: Route) -> Section | None:
    r = route.water
    if not r or not r.points:
        return None
    rows = [[f"{p.km:.1f}", p.nom + (f" ({p.etat})" if p.etat else ""), f"{p.distance_m:.0f} m",
             p.equipement or "", " / ".join(p.derniers_avis[:2])] for p in r.points]  # fmt: skip
    return Section("Eau, cabanes et refuges", ["km", "Lieu", "Écart", "Équipement", "Derniers avis"], rows,
                   [r.message, *r.avertissements, f"Source : {r.source}"])  # fmt: skip


def coverage(route: Route) -> Section | None:
    r = route.coverage
    if not r:
        return None
    rows = [[op, f"{v:g} %"] for op, v in r.par_operateur.items()]
    return Section("Réseau mobile", ["Opérateur (voix 2G/3G)", "Part du tracé"] if rows else [], rows,
                   [r.message, *r.avertissements, f"Source : {r.source}"])  # fmt: skip


def transit(route: Route) -> Section | None:
    r = route.transit
    if not r:
        return None
    rows = []
    for label, side in (("Départ", r.depart), ("Arrivée", r.arrivee)):
        for li in side.lignes if side else []:
            rows.append([label, f"{li.ligne} → {li.direction}", " ".join(li.horaires)])
    notes = [r.message]
    for label, side in (("départ", r.depart), ("arrivée", r.arrivee)):
        if side and side.arrets:
            notes.append(f"Arrêts au {label} : {', '.join(side.arrets)}")
    return Section(f"Transports en commun ({r.date:%d/%m/%Y})", ["", "Ligne", "Passages"] if rows else [], rows,
                   [*notes, f"Source : {r.source}"])  # fmt: skip


def wildlife(route: Route) -> Section | None:
    r = route.wildlife
    if not r:
        return None
    rows = [[group, " · ".join(lines)] for group, lines in r.groupes.items()]
    notes = [r.message] + [f"À connaître : {n}" for n in r.a_connaitre] + r.avertissements + [f"Source : {r.source}"]
    return Section(f"Faune observée ({r.periode})", ["Groupe", "Espèces les plus observées"] if rows else [], rows,
                   notes)  # fmt: skip


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
    builders = (
        stages,
        pois,
        technical,
        areas,
        water,
        bivouacs,
        weather,
        snow,
        avalanche,
        coverage,
        transit,
        wildlife,
        validation,
        quality,
    )
    return [s for b in builders if (s := b(route))]
