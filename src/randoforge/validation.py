"""Règles de validation d'un itinéraire (docs/10 - Architecture/Validation & cohérence.md).

Chaque règle renvoie des `Check`. Les identifiants correspondent à la documentation.
Une règle qui ne peut pas être vérifiée faute de données le dit (niveau `info`)
plutôt que de se taire.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from .core.geo import distance_m, segment_lengths
from .core.models import SAC_SCALE, Check, Route, ValidationReport, WaySegment
from .core.stats import LOOP_TOLERANCE_M
from .core.sun import sun_times, timezone_at
from .core.terrain import retraced_sections, steep_sections

DISTANCE_TOL = 0.10
D_PLUS_TOL = 0.15
PAUSE_RATIO = 1 / 6
DAYLIGHT_MARGIN = timedelta(minutes=30)
SNOW_ALT_M = 2500
SNOW_MONTHS = {11, 12, 1, 2, 3, 4, 5}
MONTHS_FR = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]
WATER_GAP_H = 3.0
STROLLER_PCT = 15.0
CHILD_MAX_MIN = 4 * 60
ON_PATH_MIN_PCT = 95.0
SUMMIT_ON_ROUTE_M = 50.0
SUMMIT_WINDOW_M = 150.0
SUMMIT_GAP_M = 15.0
GAP_M = 100.0
WAYPOINT_TOL_M = 50.0
STEEP_PCT = 35.0
STEEP_LEN_M = 100.0
TARMAC_HIGHWAYS = {
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "trunk",
    "living_street",
}
PAVED = {"asphalt", "paved", "concrete", "concrete:plates", "paving_stones", "sett"}
BUSY_ROADS = {"trunk", "primary", "secondary"}
BUSY_MIN_M = 100.0
RETRACE_MIN_M = 300.0


def _km(m: float) -> float:
    return round(m / 1000, 2)


def check_geometry(route: Route) -> list[Check]:
    checks = []
    lats = np.array([p.lat for p in route.points])
    lons = np.array([p.lon for p in route.points])
    seg = segment_lengths(lats, lons)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    for i in np.flatnonzero(seg > GAP_M)[:5]:
        checks.append(
            Check(
                id="G2",
                level="error",
                km=_km(cum[i]),
                message=f"Saut de {seg[i]:.0f} m sans géométrie entre deux points",
            )
        )

    start, end = (route.points[0].lat, route.points[0].lon), (route.points[-1].lat, route.points[-1].lon)
    if route.request.loop and distance_m(start, end) > LOOP_TOLERANCE_M:
        checks.append(
            Check(
                id="G3",
                level="error",
                message=f"Boucle demandée mais l'arrivée est à {distance_m(start, end):.0f} m du départ",
            )
        )

    for n, wp in enumerate(route.waypoints, 1):
        d = min(distance_m(wp, (p.lat, p.lon)) for p in route.points)
        if d > WAYPOINT_TOL_M:
            checks.append(
                Check(
                    id="G6",
                    level="error",
                    message=f"Point de passage n°{n} non atteint : le tracé passe à {d:.0f} m",
                    suggestion="Déplacer ce point sur un chemin (ou vérifier qu'un chemin y mène).",
                )
            )
    return checks


def tarmac_length(segments: list[WaySegment]) -> float:
    """Longueur (m, distance moteur) sur route goudronnée."""
    return sum(
        s.end_m - s.start_m
        for s in segments
        if s.tags.get("highway") in TARMAC_HIGHWAYS or s.tags.get("surface") in PAVED
    )


def check_technical(route: Route) -> list[Check]:
    if route.technical is None:
        return [Check(id="D8", level="info", message="Passages techniques non analysés (lancer analyze_route)")]
    checks = []
    for p in route.technical:
        if "glacier" in p.types:
            checks.append(
                Check(
                    id="D8",
                    level="error",
                    km=p.km,
                    message="Traversée de glacier : hors randonnée (crampons, encordement)",
                )
            )
        if "via ferrata" in p.types:
            checks.append(
                Check(
                    id="D9",
                    level="warning",
                    km=p.km,
                    message="Via ferrata : équipement spécifique obligatoire (baudrier, longes)",
                )
            )
    return checks


def check_ways(route: Route) -> list[Check]:
    if not route.segments:
        return [
            Check(
                id="A1",
                level="info",
                message="Pas de données sur les chemins empruntés (trace importée) : accès et difficulté non vérifiés",
            )
        ]
    checks = []
    total = route.segments[-1].end_m or 1
    tarmac = 0.0
    busy: list[list] = []
    no_sac_path = 0.0
    max_sac = route.request.max_sac_scale
    for s in route.segments:
        t = s.tags
        length = s.end_m - s.start_m
        if t.get("access") in {"no", "private"} or t.get("foot") in {"no", "private"}:
            checks.append(
                Check(
                    id="A1",
                    level="error",
                    km=_km(s.start_m),
                    message=f"Passage interdit aux piétons ou privé ({length:.0f} m)",
                )
            )
        if t.get("highway") in BUSY_ROADS:
            # Portions consécutives regroupées : une simple traversée de route n'est pas signalée.
            if busy and busy[-1][1] == s.start_m:
                busy[-1][1] = s.end_m
            else:
                busy.append([s.start_m, s.end_m, t["highway"]])
        if t.get("highway") in TARMAC_HIGHWAYS or t.get("surface") in PAVED:
            tarmac += length
        if t.get("highway") == "path" and "sac_scale" not in t:
            no_sac_path += length
        sac = t.get("sac_scale")
        if max_sac and sac in SAC_SCALE and SAC_SCALE.index(sac) > SAC_SCALE.index(max_sac):
            checks.append(
                Check(
                    id="D1",
                    level="error",
                    km=_km(s.start_m),
                    message=f"Difficulté {sac} sur {length:.0f} m, au-delà du maximum demandé ({max_sac})",
                    suggestion="Recalculer avec un autre point de passage pour contourner ce passage.",
                )
            )
    for start, end, kind in busy:
        if end - start >= BUSY_MIN_M:
            checks.append(
                Check(
                    id="A4",
                    level="warning",
                    km=_km(start),
                    message=f"{end - start:.0f} m sur une route fréquentée ({kind})",
                )
            )
    pct = 100 * tarmac / total
    if pct > route.request.max_tarmac_pct:
        checks.append(
            Check(
                id="A5",
                level="warning",
                message=f"{pct:.0f} % du parcours sur route goudronnée "
                f"(max souhaité {route.request.max_tarmac_pct:.0f} %)",
            )
        )
    if no_sac_path > 500 and route.stats and (route.stats.alt_max_m or 0) > 1000:
        checks.append(
            Check(
                id="Q1",
                level="info",
                message=f"{no_sac_path / 1000:.1f} km de sentiers sans difficulté renseignée dans OSM : "
                "difficulté incertaine",
            )
        )
    return checks


def check_summits(route: Route) -> list[Check]:
    """N2 : altitude officielle des sommets atteints vs MNT.

    Calibration (docs/10 - Architecture/Calibration du dénivelé.md) : les MNT représentent bien les
    sommets arrondis (Cévennes : écart médian 0 m) mais tronquent les pics acérés (Écrins : -40 m).
    Le D+ est alors sous-estimé d'autant à chaque passage au sommet.
    """
    if not route.pois or any(p.ele is None for p in route.points):
        return []
    lats = np.array([p.lat for p in route.points])
    lons = np.array([p.lon for p in route.points])
    cum = np.concatenate([[0.0], np.cumsum(segment_lengths(lats, lons))])
    eles = np.array([p.ele for p in route.points], dtype=float)
    checks = []
    for poi in route.pois:
        if poi.categorie != "sommet" or poi.type != "peak" or poi.ele is None or poi.distance_m > SUMMIT_ON_ROUTE_M:
            continue
        near = np.abs(cum - poi.km * 1000) <= SUMMIT_WINDOW_M
        dem_top = float(eles[near].max()) if near.any() else None
        if dem_top is not None and poi.ele - dem_top > SUMMIT_GAP_M:
            gap = poi.ele - dem_top
            checks.append(
                Check(
                    id="N2",
                    level="warning",
                    km=poi.km,
                    message=f"Sommet {poi.nom or ''} : altitude officielle {poi.ele:.0f} m, MNT {dem_top:.0f} m "
                    f"({-gap:.0f} m). Pic acéré mal représenté : D+ réel probablement plus élevé d'environ {gap:.0f} m",
                )
            )
    return checks


def check_numbers(route: Route) -> list[Check]:
    s = route.stats
    if s is None or s.d_plus_m is None:
        return [Check(id="N0", level="error", message="Altitudes manquantes : dénivelé non calculé")]
    checks = []
    if s.is_loop and max(s.d_plus_m, s.d_minus_m) > 0:
        gap = abs(s.d_plus_m - s.d_minus_m) / max(s.d_plus_m, s.d_minus_m)
        if gap > 0.01:
            checks.append(
                Check(
                    id="N1",
                    level="error",
                    message=f"Boucle avec D+ {s.d_plus_m:.0f} m ≠ D- {s.d_minus_m:.0f} m",
                )
            )
    start_ele = route.points[0].ele
    # Tolérance = seuil d'hystérésis : une montée inférieure au seuil n'est pas comptée.
    if (
        start_ele is not None
        and s.alt_max_m is not None
        and s.d_plus_m + s.params.threshold_m < s.alt_max_m - start_ele - 1
    ):
        checks.append(
            Check(id="N3", level="error", message="D+ inférieur à l'écart entre le départ et le point culminant")
        )

    engine_dplus = route.engine_stats.get("d_plus_m")
    if engine_dplus:
        diff = abs(s.d_plus_m - engine_dplus)
        source = (
            "le topo-guide officiel" if route.source.startswith("officiel:")
            else "OpenStreetMap" if route.source.startswith("osm:") else "le moteur de routage"
        )  # fmt: skip
        if diff > max(30, 0.15 * engine_dplus):
            checks.append(
                Check(
                    id="N5",
                    level="warning",
                    message=f"D+ calculé {s.d_plus_m:.0f} m vs {engine_dplus:.0f} m selon {source} (modèles de terrain "
                    "et méthodes différents)"
                    + (
                        f" ; fourchette plausible {s.d_plus_fourchette_m[0]}–{s.d_plus_fourchette_m[1]} m"
                        + (
                            " (contient l'autre valeur)"
                            if s.d_plus_fourchette_m[0] <= engine_dplus <= s.d_plus_fourchette_m[1]
                            else ""
                        )
                        if s.d_plus_fourchette_m
                        else ""
                    ),  # fmt: skip
                    # La calibration montre qu'aucune des deux valeurs n'est systématiquement la bonne.
                    suggestion=f"Prévoir plutôt la valeur haute ({max(s.d_plus_m, engine_dplus):.0f} m) pour l'effort "
                    "et l'horaire.",
                )
            )
    return checks


def check_slopes(route: Route) -> list[Check]:
    return [
        Check(
            id="D2",
            level="warning",
            km=_km(sec.start_m),
            message=f"Passage raide : jusqu'à {sec.value:.0f} % sur ~{sec.end_m - sec.start_m:.0f} m",
        )
        for sec in steep_sections(route.points, STEEP_PCT, STEEP_LEN_M)[:8]
    ]


def check_retrace(route: Route) -> list[Check]:
    sections = retraced_sections(route.points)
    total = sum(sec.value for sec in sections)
    if total < RETRACE_MIN_M:
        return []
    # Un aller-retour vers un sommet est souvent voulu ; il ne pose problème que si une boucle était demandée.
    level = "warning" if route.request.loop else "info"
    where = ", ".join(f"km {_km(sec.start_m):.1f}–{_km(sec.end_m):.1f}" for sec in sections[:4])
    return [
        Check(
            id="G4",
            level=level,
            km=_km(sections[0].start_m),
            message=f"{total / 1000:.1f} km parcourus deux fois (aller-retour) : {where}",
            suggestion="Ajouter un point de passage sur un autre chemin pour le retour."
            if route.request.loop
            else None,
        )
    ]


def check_pois(route: Route) -> list[Check]:
    if route.pois is None:
        return [
            Check(
                id="D7",
                level="info",
                message="Franchissements de cours d'eau non vérifiés (lancer analyze_route)",
            )
        ]
    return [
        Check(
            id="D7",
            level="warning",
            km=p.km,
            message=f"Gué{' sur ' + p.nom if p.nom else ''} : vérifier le niveau d'eau (crue, fonte des neiges)",
        )
        for p in route.pois
        if p.via == "gué"
    ]


# --- Demande, horaires, saison ------------------------------------------------------------


def _total_minutes(route: Route) -> int | None:
    if route.stages:
        return max(st.duree_min for st in route.stages)
    return route.stats.duration_min if route.stats else None


def check_request(route: Route) -> list[Check]:
    s, req = route.stats, route.request
    checks: list[Check] = []
    if not s:
        return checks
    if req.target_distance_km:
        gap = (s.distance_km - req.target_distance_km) / req.target_distance_km
        if abs(gap) > DISTANCE_TOL:
            checks.append(
                Check(
                    id="N4",
                    level="error",
                    message=f"Distance {s.distance_km:.1f} km au lieu de "
                    f"{req.target_distance_km:g} km demandés ({100 * gap:+.0f} %)",
                )
            )
    if req.target_d_plus_m and s.d_plus_m is not None:
        gap = (s.d_plus_m - req.target_d_plus_m) / req.target_d_plus_m
        if abs(gap) > D_PLUS_TOL:
            checks.append(
                Check(
                    id="N4",
                    level="error",
                    message=f"D+ {s.d_plus_m} m au lieu de {req.target_d_plus_m:g} m demandés ({100 * gap:+.0f} %)",
                )
            )
    minutes = _total_minutes(route)
    if req.max_duration_h and minutes and minutes > req.max_duration_h * 60:
        what = "l'étape la plus longue dure" if route.stages else "durée estimée"
        checks.append(
            Check(
                id="D3",
                level="error",
                message=f"{what.capitalize()} {minutes // 60}h{minutes % 60:02d} > {req.max_duration_h:g} h demandées",
            )
        )
    return checks


def check_daylight(route: Route) -> list[Check]:
    req = route.request
    minutes = _total_minutes(route)
    if not req.date or not minutes:
        return [Check(id="D4", level="info", message="Date non précisée : heure de coucher du soleil non vérifiée")]
    start = route.points[0]
    tz = timezone_at(start.lat, start.lon)
    times = sun_times(start.lat, start.lon, req.date, start.ele or 0)
    if times is None:
        return [Check(id="D4", level="info", message="Jour ou nuit polaire à cette date : vérifier l'ensoleillement")]
    sunrise, sunset = (t.astimezone(tz) for t in times)
    # Durée DIN = marche effective : on ajoute ~10 min de pause par heure de marche.
    walk = timedelta(minutes=minutes * (1 + PAUSE_RATIO))
    latest = (sunset - walk - DAYLIGHT_MARGIN).time()
    if req.start_time is None:
        return [
            Check(
                id="D4",
                level="info",
                message=f"Coucher du soleil à {sunset:%H:%M} : partir au plus tard "
                f"vers {latest:%H:%M} (pauses et marge de 30 min comprises)",
            )
        ]
    start_dt = datetime.combine(req.date, req.start_time, tzinfo=tz)
    arrival = start_dt + walk
    early = []
    if start_dt < sunrise - DAYLIGHT_MARGIN:
        early = [
            Check(id="D4", level="warning", message=f"Départ avant le lever du soleil ({sunrise:%H:%M}) : frontale")
        ]
    if arrival > sunset:
        return early + [
            Check(
                id="D4",
                level="error",
                message=f"Arrivée estimée vers {arrival:%H:%M}, après le coucher du soleil ({sunset:%H:%M})",
                suggestion=f"Partir avant {latest:%H:%M} ou raccourcir.",
            )
        ]
    if arrival > sunset - DAYLIGHT_MARGIN:
        return early + [
            Check(
                id="D4",
                level="warning",
                message=f"Arrivée vers {arrival:%H:%M}, moins de 30 min avant le coucher du soleil ({sunset:%H:%M})",
            )
        ]
    return early + [
        Check(
            id="D4", level="info", message=f"Arrivée estimée vers {arrival:%H:%M}, coucher du soleil à {sunset:%H:%M}"
        )
    ]


def check_season(route: Route) -> list[Check]:
    s = route.stats
    if not s or s.alt_max_m is None or s.alt_max_m < SNOW_ALT_M:
        return []
    month = route.request.date.month if route.request.date else None
    if month is None:
        return [Check(id="D5", level="info", message=f"Point culminant à {s.alt_max_m} m : neige possible hors été")]
    if month in SNOW_MONTHS:
        return [
            Check(
                id="D5",
                level="warning",
                message=f"Point culminant à {s.alt_max_m} m en {MONTHS_FR[month - 1]} : "
                "neige et névés probables (crampons, piolet ?)",
            )
        ]
    return []


def check_water(route: Route) -> list[Check]:
    s = route.stats
    if route.pois is None or not s or not s.duration_min or not s.distance_km:
        return []
    water_km = sorted(
        p.km
        for p in route.pois
        if p.categorie in {"eau", "lac", "cascade"} or (p.categorie == "riviere" and not p.intermittent)
    )
    marks = [0.0, *water_km, s.distance_km]
    gap_km = max(b - a for a, b in zip(marks, marks[1:], strict=False))
    gap_h = gap_km / s.distance_km * s.duration_min / 60
    if gap_h > WATER_GAP_H:
        start = next(a for a, b in zip(marks, marks[1:], strict=False) if b - a == gap_km)
        return [
            Check(
                id="D6",
                level="warning",
                km=round(start, 2),
                message=f"Aucun point d'eau connu sur {gap_km:.1f} km "
                f"(~{gap_h:.1f} h de marche) : emporter assez d'eau",
            )
        ]
    return []


# --- Réglementation et publics ------------------------------------------------------------


def check_areas(route: Route) -> list[Check]:
    if route.areas is None:
        return [Check(id="A2", level="info", message="Zones réglementées non vérifiées (lancer analyze_route)")]
    checks = []
    for a in route.areas:
        name = f" « {a.nom} »" if a.nom else ""
        if a.kind == "zone militaire":  # « zone militaire (accès autorisé) » ne bloque pas
            checks.append(
                Check(
                    id="A3",
                    level="error",
                    km=a.km_debut,
                    message=f"Traversée d'une zone militaire{name} "
                    f"(km {a.km_debut:.1f}–{a.km_fin:.1f}) : accès interdit ou réglementé",
                )
            )
            continue
        level = "info" if a.protect_class in {"5", "6"} or a.kind.startswith("parc naturel régional") else "warning"
        checks.append(
            Check(
                id="A2",
                level=level,
                km=a.km_debut,
                message=f"Traverse {a.kind}{name} (km {a.km_debut:.1f}–{a.km_fin:.1f}). " + " ".join(a.notes),
            )
        )
        if route.request.with_dog and a.chiens in {"interdits", "en laisse"}:
            lvl = "error" if a.chiens == "interdits" else "warning"
            checks.append(Check(id="C1", level=lvl, km=a.km_debut, message=f"Chiens {a.chiens} dans {a.kind}{name}"))
    return checks


def check_public(route: Route) -> list[Check]:
    req = route.request
    checks: list[Check] = []
    if req.stroller:
        bad = [
            s
            for s in route.segments
            if s.tags.get("highway") in {"path", "steps"}
            or "sac_scale" in s.tags
            or s.tags.get("tracktype") in {"grade3", "grade4", "grade5"}
        ]
        if bad:
            length = sum(s.end_m - s.start_m for s in bad)
            checks.append(
                Check(
                    id="P1",
                    level="error",
                    km=_km(bad[0].start_m),
                    message=f"{length:.0f} m de sentier, marches ou piste dégradée : impraticable en poussette",
                )
            )
        if not route.segments:
            checks.append(
                Check(id="P1", level="info", message="Trace importée : praticabilité en poussette non vérifiable")
            )
        steep = steep_sections(route.points, STROLLER_PCT)
        if steep:
            checks.append(
                Check(
                    id="P1",
                    level="warning",
                    km=_km(steep[0].start_m),
                    message=f"Pente jusqu'à {max(x.value for x in steep):.0f} % : difficile en poussette",
                )
            )
    if req.with_children:
        hard = [s for s in route.segments if s.tags.get("sac_scale") not in {None, "hiking"}]
        if hard:
            checks.append(
                Check(
                    id="E1",
                    level="warning",
                    km=_km(hard[0].start_m),
                    message="Sentiers de montagne (T2+) : vigilance avec des enfants",
                )
            )
        if route.technical:
            checks.append(
                Check(
                    id="E1",
                    level="warning",
                    km=route.technical[0].km,
                    message=f"{len(route.technical)} passage(s) technique(s) : à évaluer avec des enfants",
                )
            )
        minutes = _total_minutes(route)
        if minutes and minutes > CHILD_MAX_MIN:
            checks.append(
                Check(
                    id="E1",
                    level="warning",
                    message=f"Durée {minutes // 60}h{minutes % 60:02d} : longue pour "
                    "des enfants (vitesse famille : compute_stats walker=famille)",
                )
            )
    return checks


# --- Qualité des données et météo ----------------------------------------------------------


def check_quality(route: Route) -> list[Check]:
    q = route.quality
    if q is None:
        if not route.segments:
            return [
                Check(
                    id="G1",
                    level="info",
                    message="Trace importée : présence sur des chemins non vérifiée (lancer data_quality)",
                )
            ]
        return []
    checks = []
    if q.sur_chemin_pct is not None and q.sur_chemin_pct < ON_PATH_MIN_PCT:
        where = ", ".join(f"km {a:.1f}–{b:.1f}" for a, b in q.hors_chemin[:4])
        checks.append(
            Check(
                id="G1",
                level="error",
                km=q.hors_chemin[0][0] if q.hors_chemin else None,
                message=f"{100 - q.sur_chemin_pct:.0f} % du tracé hors chemin cartographié : {where}",
            )
        )
    if q.annee_mediane_edition and datetime.now().year - q.annee_mediane_edition > 6:
        checks.append(
            Check(
                id="Q3",
                level="info",
                message=f"Données OSM anciennes (édition médiane "
                f"{q.annee_mediane_edition}) : état des sentiers à confirmer",
            )
        )
    if q.niveau == "faible":
        checks.append(
            Check(id="Q4", level="warning", message="Confiance faible dans les données : " + " ".join(q.raisons))
        )
    return checks


def check_weather(route: Route) -> list[Check]:
    w = route.weather
    if w is None or (route.request.date and w.date != route.request.date):
        return []
    return [Check(id="W1", level="warning", message=f"Météo du {w.date:%d/%m} : {a}") for a in w.alertes]


def validate(route: Route) -> ValidationReport:
    checks = (
        check_geometry(route)
        + check_ways(route)
        + check_numbers(route)
        + check_summits(route)
        + check_slopes(route)
        + check_retrace(route)
        + check_pois(route)
        + check_technical(route)
        + check_request(route)
        + check_daylight(route)
        + check_season(route)
        + check_water(route)
        + check_areas(route)
        + check_public(route)
        + check_quality(route)
        + check_weather(route)
    )
    levels = {c.level for c in checks}
    status = "error" if "error" in levels else "warning" if "warning" in levels else "ok"
    return ValidationReport(status=status, checks=sorted(checks, key=lambda c: (c.km is None, c.km or 0)))
