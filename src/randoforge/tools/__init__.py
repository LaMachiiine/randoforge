"""Outils MCP, regroupés par thème."""

from __future__ import annotations

import functools
import json

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel

from ..app import App
from . import access, analyze, build, dossier, nature, output, search, snow, trek


class CompactServer:
    """Façade de `MCPServer` dont `tool()` renvoie au modèle un JSON compact.

    Le SDK sérialise les résultats en JSON indenté (2 espaces) : ces espaces sont facturés en jetons à chaque
    appel et relus à chaque tour suivant. Ici, même contenu structuré (validé contre le même schéma de sortie),
    mais texte sans indentation.
    """

    def __init__(self, mcp: MCPServer):
        self._mcp = mcp

    def tool(self, *args, **kwargs):
        register = self._mcp.tool(*args, **kwargs)

        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*a, **kw):
                result = fn(*a, **kw)
                if not isinstance(result, BaseModel):
                    return result
                data = result.model_dump(mode="json", by_alias=True)
                text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=data)

            register(wrapper)
            return fn

        return decorator


def register_all(mcp: MCPServer, app: App) -> None:
    compact = CompactServer(mcp)
    for module in (search, build, analyze, snow, access, nature, trek, output, dossier):
        module.register(compact, app)
