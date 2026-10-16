"""Outil MCP : faune observée autour du tracé."""

from __future__ import annotations

from datetime import date as Date
from typing import Annotated

import numpy as np
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..app import App
from ..core import wildlife as wildlife_lib
from ..core.models import WildlifeReport
from ..engines.wildlife import ATTRIBUTION, GROUPS

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]  # fmt: skip
YEARS_BACK = 10
PER_GROUP = {"mammifères": 8, "oiseaux": 10, "reptiles": 6, "amphibiens": 5}


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def wildlife(
        route_id: str, date: Date | None = None, radius_km: Annotated[float, Field(gt=0, le=10)] = 3.0
    ) -> WildlifeReport:
        """Faune **observée** autour du tracé (± `radius_km`) aux mêmes mois, sur 10 ans : mammifères, oiseaux,
        reptiles et amphibiens les plus observés (GBIF : iNaturalist, INPN, réseaux naturalistes), et espèces à
        connaître (vipères, grands prédateurs). Ce sont des observations, pas une garantie de rencontre : une espèce
        discrète peut être présente sans être signalée. Citer la source."""
        route = app.load(route_id)
        if not app.services.wildlife:
            raise ToolError("Service d'observations naturalistes non configuré.")
        day = date or route.request.date or Date.today()
        months = wildlife_lib.month_window(day.month)
        years = (day.year - YEARS_BACK, day.year)
        lats = np.array([p.lat for p in route.points])
        lons = np.array([p.lon for p in route.points])
        dlat = radius_km / 111.32
        dlon = dlat / max(0.1, float(np.cos(np.radians(lats.mean()))))
        bbox = (float(lats.min()) - dlat, float(lons.min()) - dlon, float(lats.max()) + dlat, float(lons.max()) + dlon)
        svc = app.services.wildlife
        calls = {
            g: (lambda keys=keys, g=g: app.external(lambda: svc.species_counts(bbox, months, years, keys, PER_GROUP[g])))
            for g, keys in GROUPS.items()
        }  # fmt: skip
        calls["notable"] = lambda: app.external(lambda: svc.notable_counts(bbox, months, years))
        res = app.parallel(calls)
        notable_res = res.pop("notable")
        failed = [g for g, r in res.items() if isinstance(r, ToolError)]
        if len(failed) == len(GROUPS):
            raise ToolError(f"Observations naturalistes indisponibles : {res[failed[0]]}")
        notable_counts = [] if isinstance(notable_res, ToolError) else notable_res
        keys = sorted({k for r in res.values() if not isinstance(r, ToolError) for k, _ in r[1]}
                      | {k for k, _ in notable_counts})  # fmt: skip
        names = app.parallel({str(k): (lambda k=k: app.external(lambda: svc.names(k))) for k in keys})
        groups: dict[str, list[str]] = {}
        notable: list[str] = []
        total = 0
        for g in GROUPS:
            r = res[g]
            if isinstance(r, ToolError):
                continue
            total += r[0]
            lines = []
            for key, count in r[1]:
                nm = names.get(str(key))
                sci, fr = nm if not isinstance(nm, ToolError) else (str(key), None)
                lines.append(f"{fr} ({sci}) : {count} obs." if fr else f"{sci} : {count} obs.")
            if lines:
                groups[g] = lines
        for key, count in notable_counts:
            nm = names.get(str(key))
            sci, fr = nm if not isinstance(nm, ToolError) else (str(key), None)
            if label := wildlife_lib.notable(sci):
                notable.append(f"{fr or label} ({sci}) : {count} obs. — {label}")
        period = (f"{MONTHS[months[0] - 1]}–{MONTHS[months[1] - 1]} {years[0]}–{years[1]}"
                  if months[0] != months[1] else f"{MONTHS[months[0] - 1]} {years[0]}–{years[1]}")  # fmt: skip
        warnings = [
            "Observations signalées, pas une garantie de rencontre ; les espèces discrètes sont sous-représentées."
        ]
        if failed:
            warnings.append(f"Groupes indisponibles : {', '.join(failed)}")
        if total < 30:
            warnings.append("Peu d'observations dans ce secteur : liste très incomplète.")
        message = (f"{total} observations de vertébrés autour du tracé ({period})"
                   + (f" ; à connaître : {', '.join(n.split(' (')[0] for n in notable)}" if notable else "") + ".")  # fmt: skip
        if isinstance(notable_res, ToolError):
            warnings.append("Recherche des espèces à connaître (vipères, grands prédateurs) indisponible.")
        return WildlifeReport(message=message, periode=period, groupes=groups, a_connaitre=notable,
                              source=ATTRIBUTION, avertissements=warnings)  # fmt: skip
