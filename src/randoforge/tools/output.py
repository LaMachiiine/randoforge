"""Outils de consultation, d'historique et d'export."""

from __future__ import annotations

import re
import shutil
from datetime import date as Date
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ..app import App
from ..core.models import RouteSummary
from ..formats.gpx import write_gpx
from ..formats.html import write_map
from ..formats.markdown import write_fiche
from ..formats.roadbook import write_roadbook
from .schemas import ExportResult, RouteList

Format = Literal["gpx", "md", "html", "roadbook"]


def slug(text: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", text, flags=re.UNICODE).strip()
    return re.sub(r"\s+", " ", s)[:80] or "rando"


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def get_route(route_id: str) -> RouteSummary:
        """Résumé d'un itinéraire (stats, avertissements, statut de validation), sans la géométrie."""
        return RouteSummary.of(app.load(route_id))

    @mcp.tool()
    def list_routes(done: bool | None = None) -> RouteList:
        """Liste les itinéraires enregistrés ; `done=True` : seulement les randos faites,
        `done=False` : seulement les projets."""
        routes = app.store.list()
        if done is not None:
            routes = [r for r in routes if bool(r.done_on) == done]
        return RouteList(routes=[RouteSummary.of(r) for r in routes])

    @mcp.tool()
    def mark_done(route_id: str, date: Date | None = None, notes: str | None = None) -> RouteSummary:
        """Marque une rando comme faite (date, impressions). Les boucles générées ensuite éviteront
        de repasser par les mêmes chemins (generate_loop_candidates, avoid_done)."""
        route = app.load(route_id)
        route.done_on = date or Date.today()
        route.done_notes = notes
        app.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def export_route(
        route_id: str,
        formats: list[Format] = ["gpx", "md", "html"],  # noqa: B006
        vault_dir: str | None = None,
    ) -> ExportResult:
        """Écrit les fichiers d'un itinéraire et renvoie leurs chemins, à communiquer à l'utilisateur :
        - `gpx` : montre, applis — itinéraire complet en une trace (points notables et nuits en
          waypoints) + un fichier `jour-N.gpx` par étape si plan_stages a été lancé ;
        - `md` : fiche Obsidian (frontmatter Dataview) ;
        - `html` : carte interactive (fond topo, points notables, passages techniques, profil) ;
        - `roadbook` : page imprimable (Ctrl+P → PDF) avec étapes, passages, eau, météo.
        `vault_dir` : copie aussi la fiche, le GPX et la carte dans `<vault_dir>/Randos/<nom>/`.
        """
        route = app.load(route_id)
        d = app.store.dir_for(route_id)
        writers = {
            "gpx": ("route.gpx", write_gpx),
            "md": ("fiche.md", write_fiche),
            "html": ("carte.html", write_map),
            "roadbook": ("roadbook.html", write_roadbook),
        }
        files: dict[str, str] = {}
        for fmt in formats:
            name, writer = writers[fmt]
            (d / name).write_text(writer(route), encoding="utf-8")
            files[fmt] = str(d / name)
        if "gpx" in formats:
            # Itinérance : en plus du GPX complet, un fichier par jour (pratique sur une montre).
            for old in d.glob("jour-*.gpx"):
                old.unlink()
            for stage in route.stages or []:
                path = d / f"jour-{stage.jour}.gpx"
                path.write_text(write_gpx(route, day=stage.jour), encoding="utf-8")
                files[f"gpx_jour_{stage.jour}"] = str(path)
        if vault_dir:
            vault = Path(vault_dir).expanduser()
            if not vault.is_dir():
                raise ToolError(f"Dossier du vault introuvable : {vault}")
            target = vault / "Randos" / slug(route.name)
            target.mkdir(parents=True, exist_ok=True)
            for fmt, path in list(files.items()):
                dest = target / Path(path).name
                shutil.copyfile(path, dest)
                files[f"vault_{fmt}"] = str(dest)
        return ExportResult(route_id=route_id, files=files)
