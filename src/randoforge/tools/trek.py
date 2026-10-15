"""Outils d'itinérance : emplacements de bivouac / hébergements, découpage en étapes."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..app import App
from ..core import bivouac as bivouac_lib
from ..core import stages as stages_lib
from ..core.models import Route
from .schemas import WALKERS, BivouacResult, StagesResult, Walker

REMINDERS = [
    "Bivouac : tente montée le soir et démontée le matin, petit groupe, une seule nuit au même endroit.",
    "Sans trace : pas de feu, déchets remportés, eau prélevée loin des sources, toilettes à 50 m de l'eau.",
    "La réglementation dépend du lieu (parcs, réserves, communes, propriétés privées) : vérifier avant de partir.",
]
OVERNIGHT_KINDS = {
    "refuge": {"refuge gardé", "gîte", "refuge", "cabane", "camping"},
    "bivouac": None,  # tout emplacement
    "abri": "abrite",  # seulement les emplacements avec toit ou paroi
    "indifferent": None,
}


def compute_bivouacs(app: App, route: Route) -> list[str]:
    """Remplit route.bivouacs ; renvoie les sources indisponibles."""
    failures = app.best_effort(
        route,
        (route.pois is None, app.ensure_pois, "points d'eau"),
        (route.technical is None, app.ensure_technical, "passages techniques"),
        (route.areas is None, app.ensure_areas, "zones réglementées"),
    )
    try:
        refuges = app.refuges_near(route)
    except ToolError as exc:
        refuges, failures = [], [*failures, f"refuges.info : {exc}"]
    try:
        osm = app.overpass(bivouac_lib.build_query(route.points))
    except ToolError as exc:
        osm, failures = [], [*failures, f"OSM : {exc}"]
    candidates, probes = bivouac_lib.probe_points(route.points)
    slopes = bivouac_lib.slope_from_probes(app.elevations(probes).values) if probes else []
    route.bivouacs = bivouac_lib.find_spots(
        route.points,
        route.segments,
        route.engine_stats.get("distance_m"),
        candidates,
        slopes,
        osm,
        refuges,
        route.pois or [],
        route.areas or [],
        route.technical or [],
    )
    return failures


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def find_bivouac_spots(route_id: str, abrite_seulement: bool = False) -> BivouacResult:
        """Emplacements pour dormir le long du tracé : refuges, cabanes et gîtes (refuges.info, OSM),
        aires de bivouac, et emplacements *calculés* (terrain plat < 8 %, eau à moins de 500 m si
        possible, loin des routes, hors pierriers et zones où le bivouac est interdit).

        Chaque emplacement indique sa source, le détour, la distance à l'eau et les avertissements
        réglementaires. Les emplacements calculés sont des pistes à vérifier sur place.
        `abrite_seulement` : uniquement refuges, cabanes, abris, grottes et abris sous roche
        (bivouac à l'abri de la pluie et du vent).
        """
        route = app.load(route_id)
        failures = compute_bivouacs(app, route)
        app.save(route)
        rappels = REMINDERS + [f"Source indisponible : {f}" for f in failures]
        spots = [b for b in route.bivouacs if b.abrite] if abrite_seulement else route.bivouacs
        if abrite_seulement and not spots:
            rappels.append("Aucun abri cartographié le long du tracé : prévoir une tente.")
        return BivouacResult(route_id=route_id, emplacements=spots, rappels=rappels)

    @mcp.tool()
    def plan_stages(
        route_id: str,
        days: Annotated[int | None, Field(ge=1, le=15)] = None,
        max_hours_per_day: Annotated[float | None, Field(gt=1, le=12)] = None,
        overnight: Literal["indifferent", "refuge", "bivouac", "abri"] = "indifferent",
        walker: Walker | None = None,
    ) -> StagesResult:
        """Découpe un itinéraire en étapes de plusieurs jours, avec un hébergement (refuge, cabane,
        gîte) ou un bivouac en fin de chaque étape ; `overnight="abri"` : uniquement des nuits à l'abri
        (refuge, cabane, abri, grotte, abri sous roche). Donner `days` et/ou `max_hours_per_day`
        (par défaut : la durée max enregistrée par set_constraints).

        Les durées sont équilibrées, un passage technique en fin d'étape est évité. Le GPX exporté
        contient alors une trace par jour, et la fiche une section par étape.
        """
        route = app.load(route_id)
        max_hours_per_day = max_hours_per_day or route.request.max_duration_h
        if not days and not max_hours_per_day:
            raise ToolError("Indiquer `days` ou `max_hours_per_day` (ou une durée max via set_constraints).")
        if route.stats is None or route.stats.d_plus_m is None:
            raise ToolError("Statistiques indisponibles : lancer compute_stats d'abord.")
        if route.bivouacs is None:
            compute_bivouacs(app, route)
        kinds = OVERNIGHT_KINDS[overnight]
        cuts = [
            stages_lib.Cut(m=b.km * 1000, label=b.nom or b.type, kind=b.type)
            for b in route.bivouacs
            if (kinds is None or (b.abrite if kinds == "abrite" else b.type in kinds))
            and not any("interdit" in w for w in b.avertissements)
        ]
        profile = WALKERS[walker] if walker else route.stats.profile
        try:
            stages, notes = stages_lib.plan(
                route.points,
                route.stats.params,
                profile,
                cuts,
                days,
                max_hours_per_day,
                route.technical or [],
                route.pois or [],
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        route.stages = stages
        route.validation = None
        app.save(route)
        return StagesResult(route_id=route_id, etapes=stages, notes=notes)
