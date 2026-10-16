"""Outils d'analyse : contraintes, mesures, points notables, passages techniques, zones, qualité,
météo, comparaisons et validation."""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime, timedelta
from datetime import time as Time
from typing import Annotated

import numpy as np
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..app import App
from ..core import quality as quality_lib
from ..core import weather as weather_lib
from ..core.models import (
    Check,
    ElevationParams,
    RouteSummary,
    ValidationReport,
    WalkerProfile,
    WeatherReport,
)
from ..core.osmgeom import RouteFrame
from ..core.similarity import ReferenceComparison, deviation, pct
from ..core.sun import timezone_at
from ..core.terrain import retraced_sections
from ..validation import tarmac_length
from .build import done_overlap, done_routes
from .schemas import (
    WALKERS,
    AnalysisResult,
    AnnotationResult,
    AreasResult,
    CategoryName,
    Comparison,
    ComparisonRow,
    QualityResult,
    ReferenceResult,
    SacScale,
    TechnicalResult,
    Walker,
)

FORECAST_DAYS = 15


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def set_constraints(
        route_id: str,
        target_distance_km: float | None = None,
        target_d_plus_m: float | None = None,
        max_duration_h: float | None = None,
        date: Date | None = None,
        start_time: Time | None = None,
        with_dog: bool | None = None,
        with_children: bool | None = None,
        stroller: bool | None = None,
        max_sac_scale: SacScale | None = None,
        max_tarmac_pct: float | None = None,
        loop: bool | None = None,
    ) -> RouteSummary:
        """Enregistre les contraintes de l'utilisateur sur un itinéraire ; validate_route les vérifie :
        distance et D+ visés (±10 % / ±15 %), durée max, date et heure de départ (coucher du soleil,
        neige, météo), chien (parcs et réserves), enfants, poussette, difficulté max, part de goudron.
        Seuls les paramètres fournis sont modifiés.
        """
        route = app.load(route_id)
        updates = {k: v for k, v in locals().items() if k not in {"route_id", "route"} and v is not None}
        route.request = route.request.model_copy(update=updates)
        route.validation = None
        app.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def compute_stats(
        route_id: str,
        step_m: float = 10.0,
        smooth_window_m: float = 30.0,
        threshold_m: float = 5.0,
        flat_kmh: float = 4.0,
        up_m_per_h: float = 300.0,
        down_m_per_h: float = 500.0,
        walker: Walker | None = None,
    ) -> RouteSummary:
        """Recalcule distance, D+/D-, altitudes et durée avec d'autres paramètres.

        `walker` applique un profil prédéfini qui remplace les vitesses (famille : 3 km/h et
        200 m/h en montée ; moyen : 4 km/h et 300 m/h ; sportif : 5 km/h et 450 m/h).
        Les paramètres de lissage par défaut conviennent à la plupart des cas.
        """
        route = app.load(route_id)
        params = ElevationParams(step_m=step_m, smooth_window_m=smooth_window_m, threshold_m=threshold_m)
        profile = (
            WALKERS[walker]
            if walker
            else WalkerProfile(flat_kmh=flat_kmh, up_m_per_h=up_m_per_h, down_m_per_h=down_m_per_h)
        )
        app.stats_into(route, params, profile)
        app.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def annotate_route(
        route_id: str,
        categories: list[CategoryName] | None = None,
        max_detour_m: Annotated[float, Field(ge=0, le=1000)] = 300.0,
        describe: bool = True,
        limit: Annotated[int, Field(ge=1, le=200)] = 25,
    ) -> AnnotationResult:
        """Liste les points notables le long du tracé, avec leur position au km :
        cascades, rivières traversées (gués signalés), lacs, points de vue, sommets, patrimoine…

        `describe` ajoute une courte description et le lien Wikipédia des lieux connus de Wikidata.
        Renvoie les `limit` points les plus intéressants (gués toujours inclus) ; tous sont ajoutés au GPX,
        à la carte et à la fiche.
        """
        route = app.load(route_id)
        app.ensure_pois(route, list(categories) if categories else None, max_detour_m)
        warnings = [
            f"Gué au km {p.km:.1f}{' (' + p.nom + ')' if p.nom else ''} : vérifier le niveau d'eau"
            for p in route.pois
            if p.via == "gué"
        ]
        if describe and app.services.wikidata:
            ids = list(dict.fromkeys(p.wikidata for p in route.pois if p.wikidata))[:50]
            if ids:
                try:
                    info = app.external(lambda: app.services.wikidata.describe(ids))
                    for p in route.pois:
                        if p.wikidata in info:
                            p.description = info[p.wikidata]["description"]
                            p.wikipedia_url = info[p.wikidata]["wikipedia"]
                except ToolError as exc:
                    warnings.append(f"Descriptions Wikidata indisponibles ({exc})")
        if not route.pois:
            warnings.append(
                "Aucun point notable cartographié dans OSM le long du tracé (couverture parfois incomplète)."
            )
        app.save(route)
        best = sorted(route.pois, key=lambda p: (p.via != "gué", -p.score))[:limit]
        shown = sorted(best, key=lambda p: p.km)
        return AnnotationResult(route_id=route_id, pois=shown, total=len(route.pois), warnings=warnings)

    @mcp.tool()
    def technical_passages(route_id: str) -> TechnicalResult:
        """Indique les passages techniques au km près : difficulté T3+ (échelle CAS), pentes fortes,
        via ferrata, échelles, câbles, sentier peu visible, pierriers, glaciers, dangers signalés,
        passages délicats de refuges.info. Chaque passage précise pourquoi il est signalé.
        """
        route = app.load(route_id)
        app.ensure_technical(route)
        app.save(route)
        levels = [p.niveau for p in route.technical if p.niveau]
        notes = []
        if not route.segments:
            notes.append(
                "Trace importée : difficulté OSM (sac_scale) non disponible, "
                "seuls la pente et les tags OSM sont analysés."
            )
        if any(p.a_verifier for p in route.technical):
            notes.append("Certains passages sont marqués à vérifier (possible artefact du relief).")
        return TechnicalResult(
            route_id=route_id, passages=route.technical, niveau_max=max(levels, default=None), notes=notes
        )

    @mcp.tool()
    def route_areas(route_id: str) -> AreasResult:
        """Zones réglementées traversées : parcs nationaux, réserves naturelles, zones protégées,
        terrains militaires — avec les règles probables (chiens, bivouac). Ne dit jamais « autorisé » :
        renvoie vers le règlement du site."""
        route = app.load(route_id)
        app.ensure_areas(route)
        app.save(route)
        notes = [] if route.areas else ["Aucune zone réglementée cartographiée sur le tracé."]
        return AreasResult(route_id=route_id, zones=route.areas, notes=notes)

    @mcp.tool()
    def data_quality(route_id: str) -> QualityResult:
        """Score de confiance des données (altimétrie, difficulté renseignée, fraîcheur OSM) et
        vérification que le tracé suit des chemins cartographiés (indispensable pour une trace importée)."""
        route = app.load(route_id)
        frame = RouteFrame(route.points)
        elements = app.overpass(quality_lib.build_query(frame))
        on_path_pct, off = quality_lib.on_path(frame, elements)
        route.quality = quality_lib.assess(route, on_path_pct, off, quality_lib.median_edit_year(elements))
        route.validation = None
        app.save(route)
        return QualityResult(
            route_id=route_id, qualite=route.quality, balise_pct=quality_lib.marked_share(route.segments)
        )

    @mcp.tool()
    def weather_forecast(route_id: str, date: Date | None = None, start_time: Time | None = None) -> WeatherReport:
        """Prévisions Open-Meteo sur la plage horaire de marche, au départ, au point culminant et à
        l'arrivée : températures, pluie, rafales, orage, neige au sol. Jusqu'à 15 jours à l'avance.
        Utilise la date/heure de set_constraints si elles ne sont pas fournies (départ 9 h par défaut)."""
        route = app.load(route_id)
        if not app.services.weather:
            raise ToolError("Service météo non configuré.")
        day = date or route.request.date
        if day is None:
            raise ToolError("Préciser la date (ici ou via set_constraints).")
        start = route.points[0]
        today = datetime.now(timezone_at(start.lat, start.lon)).date()
        if not 0 <= (day - today).days <= FORECAST_DAYS:
            raise ToolError(
                f"Prévisions disponibles du {today:%d/%m} au {today + timedelta(days=FORECAST_DAYS):%d/%m} "
                "seulement. Au-delà, se fier à la règle saisonnière (D5) et revenir plus tard."
            )
        t0 = start_time or route.request.start_time or Time(9, 0)
        if route.stages:
            minutes = max(s.duree_min for s in route.stages)  # plage horaire d'une journée de marche
        else:
            minutes = route.stats.duration_min if route.stats and route.stats.duration_min else 240
        hours = range(t0.hour, min(24, t0.hour + int(np.ceil(minutes * 7 / 6 / 60)) + 1))
        eles = [p.ele or 0 for p in route.points]
        top = route.points[int(np.argmax(eles))]
        places = [("départ", route.points[0]), ("point culminant", top)]
        if not route.request.loop and not (route.stats and route.stats.is_loop):
            places.append(("arrivée", route.points[-1]))
        windows = []
        for label, p in places:
            data = app.external(lambda p=p: app.services.weather.hourly(p.lat, p.lon, p.ele or 0, day))
            windows.append(weather_lib.summarize(data, label, p.ele or 0, hours))
        route.weather = WeatherReport(
            date=day, heures=f"{hours.start}h–{hours.stop}h", points=windows, alertes=weather_lib.alerts(windows)
        )
        # Demander la météo, c'est préparer le départ : on valide l'itinéraire (météo comprise) dans la foulée,
        # sans dépendre de l'agent. Les analyses manquantes tournent en parallèle.
        route.weather.analyses_indisponibles = app.validate_full(route)
        route.weather.validation_status = route.validation.status
        route.weather.alertes_itineraire = [
            f"{c.id} : {c.message}" for c in route.validation.checks if c.level in {"error", "warning"}
        ][:8]
        app.save(route)
        return route.weather

    @mcp.tool()
    def compare_routes(route_ids: Annotated[list[str], Field(min_length=2, max_length=10)]) -> Comparison:
        """Tableau comparatif de plusieurs itinéraires (distance, D+, durée, goudron, sentiers balisés,
        allers-retours, recouvrement avec les randos déjà faites, difficulté, validation)."""
        done = done_routes(app)
        rows = []
        for rid in route_ids:
            r = app.load(rid)
            s = r.stats
            levels = [p.niveau for p in r.technical or [] if p.niveau]
            engine_m = r.engine_stats.get("distance_m")
            rows.append(
                ComparisonRow(
                    route_id=rid,
                    name=r.name,
                    distance_km=s.distance_km if s else None,
                    d_plus_m=s.d_plus_m if s else None,
                    duree=s.duration_label if s else None,
                    alt_max_m=s.alt_max_m if s else None,
                    tarmac_pct=round(100 * tarmac_length(r.segments) / engine_m) if r.segments and engine_m else None,
                    balise_pct=quality_lib.marked_share(r.segments),
                    retrace_km=round(sum(sec.value for sec in retraced_sections(r.points)) / 1000, 2),
                    deja_fait_pct=round(100 * done_overlap(r, done)),
                    niveau_technique_max=max(levels, default=None),
                    n_passages_techniques=len(r.technical) if r.technical is not None else None,
                    n_pois=len(r.pois) if r.pois is not None else None,
                    validation=r.validation.status if r.validation else None,
                )
            )
        return Comparison(rows=rows)

    @mcp.tool()
    def compare_with_reference(route_id: str, reference_id: str) -> ReferenceResult:
        """Compare un itinéraire à une trace de référence (ex. GPX enregistré sur le terrain, importé
        avec import_gpx) : écart géométrique, écarts de distance et de D+. Sert à calibrer et à
        vérifier la précision des calculs."""
        route, ref = app.load(route_id), app.load(reference_id)
        mean, worst, within = deviation(route.points, ref.points)
        s, rs = route.stats, ref.stats
        comp = ReferenceComparison(
            ecart_moyen_m=round(mean, 1),
            ecart_max_m=round(worst, 1),
            part_a_moins_25m_pct=round(within, 1),
            distance_km=s.distance_km if s else None,
            distance_ref_km=rs.distance_km if rs else None,
            ecart_distance_pct=pct(s.distance_km if s else None, rs.distance_km if rs else None),
            d_plus_m=s.d_plus_m if s else None,
            d_plus_ref_m=rs.d_plus_m if rs else None,
            ecart_d_plus_pct=pct(s.d_plus_m if s else None, rs.d_plus_m if rs else None),
            ecart_distance_km=round(s.distance_km - rs.distance_km, 2) if s and rs else None,
            ecart_d_plus_m=s.d_plus_m - rs.d_plus_m
            if s and rs and s.d_plus_m is not None and rs.d_plus_m is not None
            else None,
        )
        return ReferenceResult(route_id=route_id, reference_id=reference_id, comparaison=comp)

    @mcp.tool()
    def analyze_route(route_id: str, limit_pois: Annotated[int, Field(ge=0, le=50)] = 10) -> AnalysisResult:
        """Analyse complète en UN appel : points notables, passages techniques, zones réglementées (en
        parallèle) puis validation. À préférer à annotate_route + technical_passages + route_areas +
        validate_route appelés séparément : plus rapide et moins de jetons.
        Penser à enregistrer d'abord les contraintes (set_constraints) pour qu'elles soient vérifiées.
        """
        route = app.load(route_id)
        failures = app.validate_full(route)
        app.save(route)
        pois = route.pois or []
        best = sorted(sorted(pois, key=lambda p: (p.via != "gué", -p.score))[:limit_pois], key=lambda p: p.km)
        return AnalysisResult(
            route_id=route_id,
            validation=route.validation,
            pois=best,
            pois_total=len(pois),
            passages_techniques=route.technical or [],
            zones=route.areas or [],
            indisponible=failures,
        )

    @mcp.tool()
    def validate_route(route_id: str) -> ValidationReport:
        """Vérifie l'itinéraire : géométrie, accès interdits, zones réglementées, difficulté, cohérence
        des chiffres, contraintes demandées, pentes, gués, eau, horaires, saison, météo, qualité des
        données. Statut `ok`, `warning` ou `error`, avec la position au km.

        Lance automatiquement les analyses manquantes (points notables, passages techniques, zones).
        """
        route = app.load(route_id)
        failures = app.validate_full(route)
        route.validation.checks += [
            Check(id="X0", level="info", message=f"Analyse indisponible — {f}") for f in failures
        ]
        app.save(route)
        return route.validation
