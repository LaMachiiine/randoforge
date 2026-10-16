"""Serveur MCP RandoForge : expose à Claude des outils déterministes pour les itinéraires de rando."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import __version__
from .app import App
from .services import Services
from .storage import RouteStore, default_home
from .tools import register_all

INSTRUCTIONS = """\
RandoForge fournit des outils fiables pour concevoir des itinéraires de randonnée.
Règles :
- N'annonce jamais une distance, un dénivelé, une durée ou une altitude qui ne vient pas d'un outil.
- Ne propose jamais un tracé qui n'a pas été produit par route_between, generate_loop_candidates ou importé.
- Enregistre les contraintes de l'utilisateur avec set_constraints, puis lance analyze_route (analyses + validation
  en un appel) avant de livrer ; ne livre pas un itinéraire au statut `error` sans le dire.
- Signale toujours les `warnings`, les checks de validation et les avertissements réglementaires.
Rando nommée : find_official_treks → import_official_trek, sinon find_hiking_routes → import_hiking_route,
sinon route_via_places (lieux cités par le descriptif).
Démarche type : geocode → find_pois / find_hiking_routes → route_between ou generate_loop_candidates
(+ compare_routes) → set_constraints → analyze_route → prepare_dossier (trace GPX + page unique : météo, neige,
faune, réseau, eau en itinérance ; transport=true seulement sur demande).
Plusieurs jours : find_bivouac_spots → plan_stages avant prepare_dossier. Repli : bailout_route.
"""


def build_server(store: RouteStore | None = None, services: Services | None = None) -> MCPServer:
    mcp = MCPServer("randoforge", version=__version__, instructions=INSTRUCTIONS)
    register_all(mcp, App(store or RouteStore(), services or Services.from_env(default_home())))
    return mcp


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
