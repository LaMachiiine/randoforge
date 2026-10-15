"""Outils MCP, regroupés par thème."""

from mcp.server.mcpserver import MCPServer

from ..app import App
from . import analyze, build, output, search, trek


def register_all(mcp: MCPServer, app: App) -> None:
    for module in (search, build, analyze, trek, output):
        module.register(mcp, app)
