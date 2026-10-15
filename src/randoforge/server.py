"""Serveur MCP RandoForge : expose à Claude des outils déterministes pour les itinéraires de rando."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from . import __version__
from .core.models import ElevationParams, Route, RouteSummary, WalkerProfile
from .core.stats import compute_stats as _compute_stats
from .formats.gpx import read_gpx, write_gpx
from .formats.markdown import write_fiche
from .storage import RouteStore, new_route_id

INSTRUCTIONS = """\
RandoForge fournit des outils fiables pour concevoir des itinéraires de randonnée.
Règles :
- N'annonce jamais une distance, un dénivelé, une durée ou une altitude qui ne vient pas d'un outil.
- Les itinéraires sont désignés par leur route_id ; la géométrie reste côté serveur.
- Signale toujours à l'utilisateur les `warnings` renvoyés.
"""


class RouteList(BaseModel):
    routes: list[RouteSummary]


class ExportResult(BaseModel):
    route_id: str
    files: dict[str, str]


def build_server(store: RouteStore | None = None) -> MCPServer:
    store = store or RouteStore()
    mcp = MCPServer("randoforge", version=__version__, instructions=INSTRUCTIONS)

    def load(route_id: str) -> Route:
        # Seuls les messages de ToolError sont transmis à Claude : on traduit les erreurs prévues.
        try:
            return store.load(route_id)
        except (KeyError, ValueError) as exc:
            raise ToolError(exc.args[0]) from exc

    def stats_into(route: Route, params: ElevationParams, profile: WalkerProfile) -> Route:
        source = "du fichier GPX" if route.source.startswith("gpx:") else route.source
        stats, warnings = _compute_stats(route.points, params, profile, elevation_source=source)
        route.stats, route.warnings = stats, warnings
        return route

    @mcp.tool()
    def import_gpx(path: str, name: str | None = None) -> RouteSummary:
        """Importe un fichier GPX local comme itinéraire et calcule ses statistiques.

        À utiliser pour analyser une trace existante (ex. trace enregistrée à la montre)
        ou la comparer à un itinéraire généré. Renvoie un route_id réutilisable.
        """
        file = Path(path).expanduser()
        if not file.is_file():
            raise ToolError(f"Fichier introuvable : {file}")
        gpx_name, points = read_gpx(file.read_text(encoding="utf-8"))
        if len(points) < 2:
            raise ToolError("Le GPX ne contient pas de trace exploitable (moins de 2 points).")
        route = Route(
            route_id=new_route_id(),
            name=name or gpx_name or file.stem,
            source=f"gpx:{file.name}",
            points=points,
        )
        stats_into(route, ElevationParams(), WalkerProfile())
        store.save(route)
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
    ) -> RouteSummary:
        """Recalcule distance, D+/D-, altitudes et durée d'un itinéraire avec des paramètres choisis.

        Les valeurs par défaut conviennent à la plupart des cas. Modifier le profil
        marcheur (vitesses) pour adapter la durée au niveau de l'utilisateur.
        """
        route = load(route_id)
        params = ElevationParams(step_m=step_m, smooth_window_m=smooth_window_m, threshold_m=threshold_m)
        profile = WalkerProfile(flat_kmh=flat_kmh, up_m_per_h=up_m_per_h, down_m_per_h=down_m_per_h)
        stats_into(route, params, profile)
        store.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def get_route(route_id: str) -> RouteSummary:
        """Résumé d'un itinéraire (stats, avertissements), sans la géométrie."""
        return RouteSummary.of(load(route_id))

    @mcp.tool()
    def list_routes() -> RouteList:
        """Liste les itinéraires enregistrés."""
        return RouteList(routes=[RouteSummary.of(r) for r in store.list()])

    @mcp.tool()
    def export_route(route_id: str, formats: list[Literal["gpx", "md"]] = ["gpx", "md"]) -> ExportResult:  # noqa: B006
        """Écrit les fichiers d'un itinéraire : GPX (montre, applis) et/ou fiche Markdown (Obsidian).

        Renvoie les chemins des fichiers créés, à communiquer à l'utilisateur.
        """
        route = load(route_id)
        d = store.dir_for(route_id)
        files: dict[str, str] = {}
        if "gpx" in formats:
            (d / "route.gpx").write_text(write_gpx(route), encoding="utf-8")
            files["gpx"] = str(d / "route.gpx")
        if "md" in formats:
            (d / "fiche.md").write_text(write_fiche(route), encoding="utf-8")
            files["md"] = str(d / "fiche.md")
        return ExportResult(route_id=route_id, files=files)

    return mcp


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
