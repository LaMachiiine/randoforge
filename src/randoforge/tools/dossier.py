"""Dossier de sortie : analyses utiles calculées en un appel, trace GPX et page unique (roadbook avec carte)."""

from __future__ import annotations

from datetime import date as Date
from datetime import time as Time
from datetime import timedelta

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ..app import App, Progress
from ..core.models import Route
from ..formats.gpx import write_gpx
from ..formats.roadbook import write_roadbook
from ..validation import alert_lines
from .access import compute_coverage, compute_transit, compute_water
from .analyze import FORECAST_DAYS, compute_weather
from .nature import compute_wildlife
from .output import write_outputs
from .schemas import DossierResult
from .snow import compute_avalanche, compute_snow

LABELS = {
    "weather": "météo",
    "snow": "neige",
    "avalanche": "terrain avalancheux",
    "wildlife": "faune",
    "coverage": "réseau mobile",
    "water": "eau et refuges",
    "transit": "transports",
}


def _multi_day(route: Route) -> bool:
    return bool(route.bivouacs) or len(route.stages or []) > 1


def _weather_line(route: Route) -> str:
    w = route.weather
    alertes = "; ".join(w.alertes) if w.alertes else "pas d'alerte"
    return f"Prévisions du {w.date:%d/%m}, {w.heures} : {alertes}."


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def prepare_dossier(
        route_id: str,
        date: Date | None = None,
        start_time: Time | None = None,
        transport: bool = False,
        en_raquettes: bool = False,
        vault_dir: str | None = None,
        ctx: Context | None = None,
    ) -> DossierResult:
        """Prépare la sortie en un appel et écrit deux livrables : la trace GPX (+ un fichier par jour) et une page
        unique `dossier.html` (carte, profil, étapes, passages, météo, neige, faune, réseau… imprimable en PDF).
        Analyses incluses, en parallèle :
        - toujours : faune observée à la saison, couverture mobile (France), points notables, passages, zones ;
        - météo si la date est dans les 15 jours ; enneigement (et terrain avalancheux s'il y a de la neige)
          en saison froide ou en altitude ;
        - eau et refuges en itinérance ou bivouac ;
        - transports en commun seulement si `transport=True` (demande explicite de l'utilisateur).
        Date et heure : celles de set_constraints si non fournies. Valide l'itinéraire avant d'écrire.
        `vault_dir` : copie aussi les fichiers dans `<vault_dir>/Randos/<nom>-<identifiant>/`."""
        route = app.load(route_id)
        day = date or route.request.date
        skipped: dict[str, str] = {}
        calls = {
            "snow": lambda: compute_snow(app, route, day, en_raquettes),
            "wildlife": lambda: compute_wildlife(app, route, day),
            "coverage": lambda: compute_coverage(app, route),
        }
        if day is None:
            skipped["weather"] = "pas de date (la préciser pour avoir les prévisions)"
        elif not 0 <= (day - Date.today()).days <= FORECAST_DAYS:
            skipped["weather"] = (
                f"date hors des {FORECAST_DAYS} jours de prévision : relancer prepare_dossier "
                f"à partir du {day - timedelta(days=FORECAST_DAYS):%d/%m}"
            )
        else:
            calls["weather"] = lambda: compute_weather(app, route, day, start_time)
        if _multi_day(route):
            calls["water"] = lambda: compute_water(app, route)
        else:
            skipped["water"] = "sortie à la journée (lancer water_and_huts si besoin)"
        if transport:
            calls["transit"] = lambda: compute_transit(app, route, day, start_time)
        # Les analyses de base (points notables, passages, zones) modifient l'itinéraire : un seul appel,
        # qui ne touche pas aux champs lus par les autres calculs.
        calls["base"] = lambda: app.run_missing_analyses(route)
        progress = Progress(ctx, len(calls) + 2)  # + validation et fichiers
        res = app.parallel(calls, on_done=lambda name: progress.step(f"{LABELS.get(name, 'analyses de base')} : fait"))

        res.pop("base")
        failures: list[str] = []
        reports = {}
        for name, r in res.items():
            if isinstance(r, ToolError):
                failures.append(f"{LABELS[name]} : {r}")
            else:
                reports[name] = r
        snow = reports.get("snow")
        if snow and snow.applicable and (snow.part_enneigee_pct or 0) > 0:
            try:
                reports["avalanche"] = compute_avalanche(app, route, snow)
            except ToolError as exc:
                failures.append(f"{LABELS['avalanche']} : {exc}")
        for name, report in reports.items():
            setattr(route, name, report)
        progress.step("validation")
        failures[:0] = app.validate_full(route)  # ne relance que les analyses de base qui ont échoué
        app.save(route)

        progress.step("écriture de la trace et du dossier")
        files = write_outputs(
            app,
            route,
            {"gpx": ("route.gpx", write_gpx), "dossier": ("dossier.html", lambda r: write_roadbook(r, with_map=True))},
            vault_dir,
        )
        if snow and not snow.applicable:
            skipped["snow"] = snow.message
        sections = {
            LABELS[name]: _weather_line(route) if name == "weather" else report.message
            for name, report in reports.items()
            if name not in skipped
        }
        return DossierResult(
            route_id=route_id,
            files=files,
            sections=sections,
            non_inclus={LABELS[k]: v for k, v in skipped.items()},
            indisponibles=failures,
            validation_status=route.validation.status if route.validation else None,
            alertes=alert_lines(route.validation),
        )
