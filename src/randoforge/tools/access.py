"""Outils MCP d'accès : transports en commun (et couverture mobile)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as Date
from datetime import time as Time
from typing import Annotated

import numpy as np
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from shapely.geometry import Point

from ..app import App
from ..core import transit as transit_lib
from ..core.geo import cumulative_distance, distance_m
from ..core.models import (
    MobileCoverageReport,
    TransitLine,
    TransitReport,
    TransitSide,
    WaterHutPoint,
    WaterHutsReport,
)
from ..core.osmgeom import RouteFrame
from ..core.sun import timezone_at
from ..engines import coverage as coverage_lib
from ..engines.transit import ATTRIBUTION
from ..validation import PAUSE_RATIO

RADIUS_M = 800  # arrêts à moins de 800 m du départ ou de l'arrivée
MAX_LINES = 8
MAX_TIMES = 14
SAME_PLACE_M = 300  # départ et arrivée confondus (boucle) : une seule recherche


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] + ("" if text.endswith(".") else ".")


def _side(stops: transit_lib.Stops) -> TransitSide:
    return TransitSide(
        arrets=[f"{n} ({d} m)" for n, d in stops.arrets[:5]],
        lignes=[
            TransitLine(ligne=li.ligne, direction=li.direction, horaires=li.horaires[:MAX_TIMES])
            for li in stops.lignes[:MAX_LINES]
        ],  # fmt: skip
        premier_retour=" ".join(stops.premier_apres) if stops.premier_apres else None,
    )


COVERAGE_STEP_M = 200
FRANCE_BBOX = (41.2, -5.5, 51.2, 9.8)  # France métropolitaine (sud, ouest, nord, est)
LEVELS = {"TBC": 3, "BC": 2, "CL": 1}
WATER_HUT_TYPES = {"point d'eau", "cabane non gardée", "refuge gardé", "gîte d'étape", "abri naturel"}
EQUIPMENT = {"poele": "poêle", "cheminee": "cheminée", "couvertures": "couvertures", "latrines": "latrines",
             "eau": "eau à moins de 100 m"}  # fmt: skip
COMMENT_CHARS = 220


def _equipment(r: dict) -> str | None:
    info = r.get("info") or {}
    parts = [f"{r['places']} places"] if r.get("places") else []
    parts += [label for key, label in EQUIPMENT.items() if info.get(key) == "Oui"]
    if info.get("manque_un_mur") == "Oui":
        parts.append("il manque un mur")
    return ", ".join(parts) or None


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def public_transport(route_id: str, date: Date | None = None, start_time: Time | None = None) -> TransitReport:
        """Transports en commun le jour de la sortie (Europe, horaires théoriques des réseaux, sans voiture) :
        arrêts à moins de 800 m du départ et de l'arrivée, passages par ligne et direction, et **premier passage
        après l'arrivée estimée** (pauses comprises) pour le retour. Défauts : date et heure de set_constraints,
        sinon aujourd'hui à 9 h. Citer la source (Transitous)."""
        route = app.load(route_id)
        if not app.services.transit:
            raise ToolError("Service d'horaires non configuré.")
        day = date or route.request.date or Date.today()
        start = start_time or route.request.start_time or Time(9, 0)
        a, b = route.points[0], route.points[-1]
        tz = timezone_at(a.lat, a.lon)
        day_start = datetime.combine(day, Time(4, 0), tzinfo=tz).astimezone(UTC)  # premiers services du matin
        finish = None
        if route.stats and route.stats.duration_min:
            walk = timedelta(minutes=route.stats.duration_min * (1 + PAUSE_RATIO))
            finish = datetime.combine(day, start, tzinfo=tz) + walk
        loop = distance_m((a.lat, a.lon), (b.lat, b.lon)) <= SAME_PLACE_M
        calls = {
            "depart": lambda: app.external(lambda: app.services.transit.stop_times(a.lat, a.lon, day_start, RADIUS_M))
        }
        if not loop:
            calls["arrivee"] = lambda: app.external(
                lambda: app.services.transit.stop_times(b.lat, b.lon, day_start, RADIUS_M)
            )
        res = app.parallel(calls)
        if all(isinstance(r, ToolError) for r in res.values()):
            raise ToolError("Horaires indisponibles : " + " ; ".join(str(r) for r in res.values()))
        dep = None if isinstance(res["depart"], ToolError) else transit_lib.group(
            res["depart"], a.lat, a.lon, tz, day, finish if loop else None)  # fmt: skip
        arr = None
        if not loop and not isinstance(res.get("arrivee"), ToolError):
            arr = transit_lib.group(res["arrivee"], b.lat, b.lon, tz, day, finish)
        parts = []
        for label, side in (("départ", dep), ("arrivée", arr)):
            if side is not None and not side.lignes:
                parts.append(f"aucun arrêt desservi le {day:%d/%m} à moins de {RADIUS_M} m de l'{label}"
                             if label == "arrivée" else f"aucun arrêt desservi le {day:%d/%m} à moins de {RADIUS_M} m du départ")  # fmt: skip
        back = (arr or dep).premier_apres if (arr or dep) else None
        if back:
            parts.append(f"premier passage après l'arrivée estimée ({finish:%H:%M}) : {back[0]}, ligne {back[1]} "
                         f"vers {back[2]}")  # fmt: skip
        elif finish and (arr or dep) and (arr or dep).lignes:
            parts.append(f"plus aucun passage après l'arrivée estimée ({finish:%H:%M})")
        return TransitReport(
            message=_sentence("; ".join(parts) or "arrêts desservis au départ et à l'arrivée"),
            date=day,
            depart=_side(dep) if dep else None,
            arrivee=_side(arr) if arr else None,
            arrivee_estimee=finish.strftime("%H:%M") if finish else None,
            source=ATTRIBUTION,
        )

    @mcp.tool()
    def water_and_huts(
        route_id: str,
        max_distance_m: Annotated[float, Field(gt=0, le=2000)] = 500,
        limit: Annotated[int, Field(ge=1, le=40)] = 15,
    ) -> WaterHutsReport:
        """Points d'eau, cabanes, refuges et gîtes à moins de `max_distance_m` du tracé (refuges.info), dans l'ordre
        de marche : **état signalé** (source tarie ou intermittente, cabane fermée ou détruite), équipement (places,
        poêle, couvertures…) et **derniers avis datés** des visiteurs pour juger de l'état récent. Citer la source.
        Les points taris ou détruits sont listés pour information mais jamais comptés comme eau ni abri."""
        route = app.load(route_id)
        refs = [r for r in app.refuges_near(route, max_distance_m + 100) if r["type"] in WATER_HUT_TYPES]
        frame = RouteFrame(route.points)
        located = []
        for r in refs:
            x, y = frame.proj.to_xy(r["lat"], r["lon"])
            pt = Point(x, y)
            dist = frame.line.distance(pt)
            if dist <= max_distance_m:
                located.append((frame.km_of(pt) / 1000, dist, r))
        located.sort(key=lambda t: t[0])
        located = located[:limit]
        warnings: list[str] = []
        comments: dict[int, list[dict]] = {}
        ids = [r["id"] for _, _, r in located if r.get("id")]
        if ids and hasattr(app.services.refuges, "comments"):
            try:
                comments = app.external(lambda: app.services.refuges.comments(ids))
            except ToolError as exc:
                warnings.append(f"Commentaires refuges.info indisponibles : {exc}")
        points = []
        for km, dist, r in located:
            avis = [
                f"{c['date'][8:10]}/{c['date'][5:7]}/{c['date'][:4]} : "
                f"{' '.join(c['texte'].split())[:COMMENT_CHARS]}" + (f" ({c['auteur']})" if c["auteur"] else "")
                for c in comments.get(r.get("id"), [])
            ]  # fmt: skip
            points.append(WaterHutPoint(
                km=round(km, 2), type=r["type"], nom=r["nom"] or r["type"], distance_m=round(dist),
                etat=r.get("etat") or None, equipement=_equipment(r), derniers_avis=avis, lien=r.get("lien"),
            ))  # fmt: skip
        water = [p for p in points if p.type == "point d'eau"]
        dry = [p for p in water if p.etat and "tari" in p.etat.lower()]
        intermittent = [p for p in water if p.etat and "intermittent" in p.etat.lower()]
        huts = [p for p in points if p.type != "point d'eau"]
        parts = [f"{len(water)} point(s) d'eau" + (f" dont {len(intermittent)} intermittent(s)" if intermittent else "")
                 + (f" et {len(dry)} tari(s)" if dry else ""), f"{len(huts)} cabane(s), refuge(s) ou gîte(s)"]  # fmt: skip
        closed = [p.nom for p in huts if p.etat]
        if closed:
            parts.append(f"état signalé : {', '.join(f'{p.nom} ({p.etat})' for p in huts if p.etat)}")
        message = "; ".join(parts) + f" à moins de {max_distance_m:g} m du tracé."
        return WaterHutsReport(message=message[:1].upper() + message[1:], points=points, avertissements=warnings)

    @mcp.tool()
    def mobile_coverage(route_id: str) -> MobileCoverageReport:
        """Couverture mobile **théorique** le long du tracé (France uniquement, carte Arcep « Mon réseau mobile ») :
        part du tracé où au moins un opérateur passe en voix (pour appeler les secours), tronçons sans réseau, 4G,
        détail par opérateur. Déclarée par les opérateurs, à l'extérieur : non garantie (relief, météo). Le 112
        passe par tout réseau disponible, même sans carte SIM de cet opérateur."""
        route = app.load(route_id)
        if not app.services.coverage:
            raise ToolError("Service de couverture mobile non configuré.")
        lats = np.array([p.lat for p in route.points])
        lons = np.array([p.lon for p in route.points])
        cum = cumulative_distance(lats, lons)
        idx = np.unique(np.minimum(np.searchsorted(cum, np.arange(0, cum[-1] + 1, COVERAGE_STEP_M)), len(lats) - 1))
        if (
            not FRANCE_BBOX[0] <= float(lats.mean()) <= FRANCE_BBOX[2]
            or not FRANCE_BBOX[1] <= float(lons.mean()) <= FRANCE_BBOX[3]
        ):
            return MobileCoverageReport(message="Couverture mobile disponible seulement en France métropolitaine.",
                                        source=coverage_lib.ATTRIBUTION)  # fmt: skip
        located = [(k, *coverage_lib.tile_of(float(lats[i]), float(lons[i]))) for k, i in enumerate(idx)]
        tiles = sorted({(x, y) for _, x, y, _, _ in located})
        res = app.parallel({f"{x}/{y}": (lambda x=x, y=y: app.external(lambda: app.services.coverage.tile(x, y)))
                            for x, y in tiles})  # fmt: skip
        failed = [k for k, v in res.items() if isinstance(v, ToolError)]
        if len(failed) == len(tiles):
            raise ToolError(f"Carte de couverture de l'Arcep indisponible : {res[failed[0]]}")
        voice = np.zeros(len(idx), dtype=int)  # meilleur niveau voix tous opérateurs : 0 rien, 1 CL, 2 BC, 3 TBC
        data4g = np.zeros(len(idx), dtype=bool)
        known = np.ones(len(idx), dtype=bool)
        per_op = {name: np.zeros(len(idx), dtype=bool) for name in coverage_lib.OPERATORS.values()}
        dates = set()
        for k, x, y, px, py in located:
            shapes = res[f"{x}/{y}"]
            if isinstance(shapes, ToolError):
                known[k] = False
                continue
            pt = Point(px, py)
            for geom, props in shapes:
                if not geom.contains(pt):
                    continue
                dates.add(str(props.get("date", ""))[:10])
                if props.get("techno") == "2G3G":
                    voice[k] = max(voice[k], LEVELS.get(props.get("niveau"), 1))
                    if (name := coverage_lib.OPERATORS.get(int(props.get("operateur", 0)))) is not None:
                        per_op[name][k] = True
                elif props.get("techno") == "4G":
                    data4g[k] = True
        n = int(known.sum()) or 1

        def pct(mask: np.ndarray) -> float:
            return round(100 * float((mask & known).sum()) / n)

        holes = []
        # Réseau utilisable pour appeler : voix 2G/3G ou 4G (appels en 4G, y compris le 112).
        reachable = (voice > 0) | data4g
        no_voice = np.flatnonzero(~reachable & known)
        if len(no_voice):
            for run in np.split(no_voice, np.flatnonzero(np.diff(no_voice) > 1) + 1):
                a, b = cum[idx[run[0]]], cum[idx[min(run[-1] + 1, len(idx) - 1)]]
                if b - a >= COVERAGE_STEP_M:
                    holes.append(f"km {a / 1000:.1f}–{b / 1000:.1f}")
        voix = pct(voice > 0)
        message = (f"Réseau mobile (voix 2G/3G ou 4G, au moins un opérateur) sur {pct(reachable)} % du tracé"
                   + (f" ; sans réseau : {', '.join(holes)}" if holes else "") + ".")  # fmt: skip
        warnings = ["Couverture théorique, à l'extérieur : non garantie (relief, forêt, météo)."]
        if holes:
            warnings.append("Le 112 passe par tout réseau disponible, même sans abonnement chez cet opérateur.")
        if failed:
            warnings.append(
                f"{len(failed)} tuile(s) de la carte indisponible(s) : couverture inconnue sur une partie du tracé."
            )
        quarter = max(dates) if dates and max(dates) else ""
        return MobileCoverageReport(
            message=message, reseau_pct=pct(reachable), voix_pct=voix, voix_bonne_pct=pct(voice >= 2), donnees_4g_pct=pct(data4g),
            zones_sans_reseau=holes, par_operateur={name: pct(mask) for name, mask in per_op.items()},
            source=coverage_lib.ATTRIBUTION + (f", données au {quarter}" if quarter else ""),
            avertissements=warnings,
        )  # fmt: skip
