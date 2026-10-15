"""Stockage des itinéraires : un dossier par itinéraire, `route.json` comme source de vérité."""

from __future__ import annotations

import os
import re
import secrets
from datetime import date
from pathlib import Path

from .core.models import Route

ROUTE_ID_RE = re.compile(r"^r_\d{4}-\d{2}-\d{2}_[0-9a-f]{6}$")


def default_home() -> Path:
    return Path(os.environ.get("RANDOFORGE_HOME", Path.home() / ".randoforge"))


def new_route_id() -> str:
    return f"r_{date.today().isoformat()}_{secrets.token_hex(3)}"


class RouteStore:
    def __init__(self, home: Path | None = None):
        self.routes_dir = (home or default_home()) / "routes"
        self.routes_dir.mkdir(parents=True, exist_ok=True)

    def dir_for(self, route_id: str) -> Path:
        # route_id vient de Claude : on refuse tout ce qui pourrait sortir du dossier.
        if not ROUTE_ID_RE.match(route_id):
            raise ValueError(f"route_id invalide : {route_id!r}")
        return self.routes_dir / route_id

    def save(self, route: Route) -> Path:
        d = self.dir_for(route.route_id)
        d.mkdir(exist_ok=True)
        (d / "route.json").write_text(route.model_dump_json(indent=1), encoding="utf-8")
        return d

    def load(self, route_id: str) -> Route:
        path = self.dir_for(route_id) / "route.json"
        if not path.exists():
            raise KeyError(f"Itinéraire inconnu : {route_id}. Utilise list_routes pour voir les itinéraires.")
        return Route.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[Route]:
        return [
            Route.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(self.routes_dir.glob("r_*/route.json"))
        ]
