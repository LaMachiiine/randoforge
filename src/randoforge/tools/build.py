"""Outils de construction de tracés : point à point, boucles automatiques, import, repli."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import numpy as np
from gpxpy.gpx import GPXException
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..app import App
from ..core import loops
from ..core.geo import cumulative_distance, distance_m, interp_lon
from ..core.models import Route, RouteRequest, RouteSummary, TrackPoint
from ..core.osmgeom import chain_route_relation, declared_values
from ..core.places import best_sequence, normalize, outliers
from ..core.quality import marked_share
from ..core.similarity import overlap_fraction
from ..core.terrain import retraced_sections
from ..engines.geotrek import INSTANCES
from ..formats.gpx import read_gpx
from ..http import HOST_LIMITS
from ..storage import new_route_id
from ..validation import tarmac_length
from .schemas import (
    Catalogue,
    LatLon,
    LoopCandidate,
    LoopCandidates,
    PlacesRoute,
    Profile,
    ResolvedPlace,
    SacScale,
)

# Brouillons en parallèle : autant que le serveur BRouter accepte de requêtes simultanées (au-delà, ils attendraient).
MAX_PLACE_DETOUR_KM = 3.0  # lieu à plus de 3 km de tous ses voisins (et 3× l'écart habituel) : douteux
MAX_IMPORT_KM = 300  # au-delà : ~30 000 altitudes à demander et un stockage lourd ; importer par étapes
PARALLEL_ROUTES = 4  # serveur sans limite connue (ex. BRouter local)


def parallel_routes(app: App) -> int:
    host = urlsplit(getattr(app.services.router, "base_url", "")).hostname or ""
    return HOST_LIMITS.get(host, (PARALLEL_ROUTES, 0.0))[0]


COMPASS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def done_routes(app: App) -> list[Route]:
    """Randos marquées comme faites (à charger une fois par appel d'outil : la lecture du stockage coûte cher)."""
    return [r for r in app.store.list() if r.done_on]


def done_overlap(route: Route, done: list[Route]) -> float:
    return max((overlap_fraction(route.points, d.points) for d in done if d.route_id != route.route_id), default=0.0)


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def route_between(
        waypoints: Annotated[list[LatLon], Field(min_length=2, max_length=30)],
        profile: Profile = "hiking-mountain",
        loop: bool = False,
        name: str | None = None,
        max_sac_scale: SacScale | None = None,
    ) -> RouteSummary:
        """Calcule un tracé sur de vrais chemins passant par les points donnés, dans l'ordre.

        - `loop=True` : revient au premier point (boucle). Pour une boucle via un lieu imposé
          (cascade, sommet), donner départ + lieu(x) avec loop=True.
        - `max_sac_scale` : difficulté maximale acceptée (hiking = T1 facile … alpine_hiking = T4).
        Jusqu'à 30 points : suffisant pour une itinérance de plusieurs jours.
        Distance et dénivelé sont recalculés sur un MNT précis (IGN en France, Copernicus ailleurs).
        """
        required = [(w.lat, w.lon) for w in waypoints]
        wps = required + [required[0]] if loop and required[0] != required[-1] else list(required)
        route = app.make_route(
            wps,
            required,
            profile,
            RouteRequest(loop=loop, max_sac_scale=max_sac_scale),
            name or f"Itinéraire {profile}",
        )
        app.save(route)
        return RouteSummary.of(route)

    def local_candidates(places: list[str], origin: tuple[float, float], max_km: float) -> dict[str, list]:
        """Candidats (lat, lon, nom) de chaque lieu autour du départ : recherche de lieux bornée à la zone, plus
        tout objet OSM portant exactement ce nom (lieu-dit, ruine, source, croix…), en une seule requête."""
        out: dict[str, list[tuple[float, float, str]]] = {p: [] for p in places}
        for place in dict.fromkeys(places):
            try:
                hits = app.external(
                    lambda p=place: app.services.nominatim.geocode(p, 10, None, origin, within_km=max_km)
                )
            except ToolError:
                hits = []
            out[place] += [(h.lat, h.lon, h.display_name.split(",")[0]) for h in hits]
        wanted = {normalize(p): p for p in places}
        pattern = "|".join(re.sub(r"[^\w\s-]", ".", p.strip()) for p in dict.fromkeys(places))
        q = (f'[out:json][timeout:25];nwr["name"~"^({pattern})$",i]'
             f"(around:{max_km * 1000:.0f},{origin[0]},{origin[1]});out center 50;")  # fmt: skip
        try:
            for el in app.overpass(q):
                c, name = el.get("center") or el, el.get("tags", {}).get("name", "")
                if c.get("lat") is not None and normalize(name) in wanted:
                    out[wanted[normalize(name)]].append((c["lat"], c["lon"], name))
        except ToolError:
            pass  # la recherche de lieux suffit souvent
        return {p: [c for c in cands if distance_m(origin, c[:2]) <= max_km * 1000] for p, cands in out.items()}

    @mcp.tool()
    def route_via_places(
        start: LatLon,
        places: Annotated[list[str], Field(min_length=1, max_length=20)],
        loop: bool = True,
        end: LatLon | None = None,
        max_km_from_start: Annotated[float, Field(gt=0, le=40)] = 12.0,
        profile: Profile = "hiking-mountain",
        name: str | None = None,
        max_sac_scale: SacScale | None = None,
    ) -> PlacesRoute:
        """Reconstruit une rando **décrite par ses lieux de passage** (descriptif de topo, récit, souvenir) quand
        son tracé n'existe nulle part : `places` = hameaux, cols, sommets, ponts, lacs… dans l'ordre de marche.
        Chaque lieu est cherché près du départ (à moins de `max_km_from_start`, lieux-dits OSM compris) ; entre
        homonymes, la suite de lieux la plus courte dans l'ordre de marche est retenue. L'itinéraire est ensuite
        tracé par ces lieux sur de vrais chemins. Les lieux introuvables sont listés (`non_trouves`), jamais devinés.
        Donner les lieux tels que cités, un par étape (hameau, col, sommet), sans les rues ni les directions.
        Préférer d'abord find_official_treks puis find_hiking_routes : un tracé officiel ou balisé est plus sûr.
        """
        origin = (start.lat, start.lon)
        by_place = local_candidates(places, origin, max_km_from_start)
        options = [(p, by_place[p]) for p in places if by_place[p]]  # (lieu cité, candidats), ordre de marche
        missing = [p for p in places if not by_place[p]]
        # Parmi les homonymes, la suite de lieux la plus courte dans l'ordre de marche (un homonyme lointain
        # allongerait le parcours) ; arrivée = départ pour une boucle.
        finish = (end.lat, end.lon) if end else (origin if loop else None)
        picks = best_sequence(origin, [[(la, lo) for la, lo, _ in c] for _, c in options], finish)
        chosen = [cands[k] for (_, cands), k in zip(options, picks, strict=True)]
        # Un lieu qui impose un grand détour (seul homonyme connu, loin de ses voisins) n'est pas suivi.
        far = set(outliers(origin, [c[:2] for c in chosen], finish, MAX_PLACE_DETOUR_KM))
        doubtful = [options[i][0] for i in sorted(far)]
        found = [
            ResolvedPlace(lieu=place, trouve=c[2], lat=c[0], lon=c[1],
                          km_du_depart=round(distance_m(origin, c[:2]) / 1000, 1))
            for i, ((place, _), c) in enumerate(zip(options, chosen, strict=True)) if i not in far
        ]  # fmt: skip
        if not found:
            raise ToolError(
                f"Aucun lieu trouvé à moins de {max_km_from_start:g} km du départ : {', '.join(places)}. "
                "Vérifier l'orthographe, élargir max_km_from_start ou donner des coordonnées à route_between."
            )
        required = [origin, *((p.lat, p.lon) for p in found)] + ([(end.lat, end.lon)] if end else [])
        wps = required + [origin] if loop and not end else list(required)
        route = app.make_route(
            wps, required, profile, RouteRequest(loop=loop and not end, max_sac_scale=max_sac_scale),
            name or "Rando reconstruite d'après ses lieux de passage",
        )  # fmt: skip
        notes = [f"Lieu introuvable près du départ, ignoré : {m}" for m in missing] + [
            f"Lieu trouvé seulement loin du parcours (homonyme ?), ignoré : {d}" for d in doubtful
        ]
        if notes:
            route.elevation_notes = route.elevation_notes + notes  # notes de source : gardées à chaque recalcul
            route.warnings = route.warnings + notes
        app.save(route)
        return PlacesRoute(route=RouteSummary.of(route), lieux=found, non_trouves=missing, douteux=doubtful)

    @mcp.tool()
    def generate_loop_candidates(
        start: LatLon,
        distance_km: Annotated[float, Field(ge=2, le=60)],
        d_plus_m: Annotated[float | None, Field(ge=0, le=5000)] = None,
        n: Annotated[int, Field(ge=1, le=5)] = 3,
        directions: Annotated[int, Field(ge=3, le=12)] = 6,
        profile: Profile = "hiking-mountain",
        max_sac_scale: SacScale | None = None,
        avoid_done: bool = True,
        name: str | None = None,
    ) -> LoopCandidates:
        """Génère automatiquement des boucles depuis un départ pour une distance (et un D+) cible,
        dans plusieurs directions, et renvoie les `n` meilleures, déjà mesurées sur le MNT.

        Classement : écart à la distance et au D+ demandés, pénalité pour les allers-retours et le
        goudron, bonus pour les sentiers balisés ; `avoid_done` pénalise les boucles qui reprennent
        des randos marquées comme faites (mark_done). Prévoir ~20–40 s.
        """
        origin = (start.lat, start.lon)
        target_m = distance_km * 1000
        request = RouteRequest(
            loop=True, max_sac_scale=max_sac_scale, target_distance_km=distance_km, target_d_plus_m=d_plus_m
        )

        def draft_direction(bearing: float) -> tuple[float, Route | None, int, int]:
            """Brouillon de boucle dans une direction : un essai + une correction de taille."""
            radius = loops.initial_radius(target_m)
            best: Route | None = None
            tried = failed = 0
            for _ in range(2):
                tried += 1
                try:
                    draft = app.make_route(
                        loops.triangle(origin, bearing, radius),
                        [origin],
                        profile,
                        request.model_copy(),
                        "",
                        with_dem=False,
                    )
                except ToolError:
                    failed += 1
                    break
                # Épingles vers les sommets du triangle (points d'attraction arbitraires) : retirées.
                draft.points, draft.segments, cut = loops.remove_spurs(draft.points, draft.segments, [origin])
                if cut and draft.engine_stats.get("distance_m"):
                    draft.engine_stats["distance_m"] -= cut
                actual = draft.engine_stats.get("distance_m") or 0
                if best is None or abs(actual - target_m) < abs(best.engine_stats.get("distance_m", 0) - target_m):
                    best = draft
                if abs(actual - target_m) / target_m < 0.08:
                    break
                radius = loops.corrected_radius(radius, target_m, actual)
            return bearing, best, tried, failed

        # Toutes les directions en parallèle (le moteur de routage répond en 1–3 s par tracé).
        with ThreadPoolExecutor(max_workers=parallel_routes(app)) as pool:
            results = list(pool.map(draft_direction, loops.bearings(directions)))
        tried = sum(r[2] for r in results)
        failed = sum(r[3] for r in results)
        drafts: list[tuple[float, Route, float, float]] = [  # (direction, tracé, aller-retour m, goudron m)
            (bearing, best, sum(sec.value for sec in retraced_sections(best.points)), tarmac_length(best.segments))
            for bearing, best, _, _ in results
            if best is not None
        ]
        if not drafts:
            raise ToolError(
                "Aucune boucle trouvée : le départ est peut-être loin de tout chemin. Essayer geocode ou find_pois."
            )

        history = done_routes(app) if avoid_done else []

        def extra(r: Route) -> tuple[float, float]:
            marked = (marked_share(r.segments) or 0) / 100
            return marked, done_overlap(r, history) if avoid_done else 0.0

        def pre_score(d) -> float:
            _, r, retrace, tarmac = d
            return loops.score(r.engine_stats["distance_m"], target_m, None, None, retrace, tarmac, *extra(r)).total

        # Mesure fine (MNT) seulement pour les meilleurs brouillons : économise les appels d'altimétrie.
        scored = []
        shortlist = sorted(drafts, key=pre_score)[: n + 2]
        with ThreadPoolExecutor(max_workers=len(shortlist) or 1) as pool:
            list(pool.map(lambda d: (app.apply_dem(d[1]), app.stats_into(d[1])), shortlist))
        for bearing, r, retrace, tarmac in shortlist:
            marked, done = extra(r)
            sc = loops.score(
                r.stats.distance_km * 1000, target_m, r.stats.d_plus_m, d_plus_m, retrace, tarmac, marked, done
            )
            scored.append((sc.total, bearing, r, retrace, tarmac, marked, done))
        scored.sort(key=lambda x: x[0])

        candidates = []
        for i, (total, bearing, r, retrace, tarmac, marked, done) in enumerate(scored[:n], 1):
            r.name = f"{name or 'Boucle'} {i} ({COMPASS[round(bearing / 45) % 8]})"
            app.save(r)
            candidates.append(
                LoopCandidate(
                    route=RouteSummary.of(r),
                    bearing_deg=bearing,
                    retrace_km=round(retrace / 1000, 2),
                    tarmac_pct=round(100 * tarmac / max(1.0, r.engine_stats.get("distance_m", 0))),
                    balise_pct=round(100 * marked),
                    deja_fait_pct=round(100 * done),
                    score=round(total, 3),
                )
            )
        notes = []
        if d_plus_m and all(abs((c.route.stats.d_plus_m or 0) - d_plus_m) / d_plus_m > 0.25 for c in candidates):
            notes.append(
                "Aucune boucle n'approche le D+ demandé à 25 % près : "
                "le relief autour du départ ne s'y prête peut-être pas."
            )
        if failed:
            notes.append(f"{failed} essai(s) sans chemin praticable.")
        return LoopCandidates(candidates=candidates, tried=tried, failed=failed, notes=notes)

    @mcp.tool()
    def import_gpx(path: str, name: str | None = None, elevation: Literal["dem", "file"] = "dem") -> RouteSummary:
        """Importe un fichier GPX local comme itinéraire et calcule ses statistiques.

        `elevation="dem"` (défaut) recalcule les altitudes sur le MNT, pour des chiffres comparables
        aux itinéraires générés ; `"file"` garde celles du fichier (ex. altimètre barométrique).
        Lancer ensuite data_quality pour vérifier que la trace suit des chemins (règle G1).
        """
        file = Path(path).expanduser()
        if not file.is_file():
            raise ToolError(f"Fichier introuvable : {file}")
        try:
            gpx_name, points = read_gpx(file.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, ValueError, GPXException) as exc:  # ValueError : coordonnées hors bornes
            raise ToolError(f"GPX illisible ({file.name}) : {exc}") from exc
        if len(points) < 2:
            raise ToolError("Le GPX ne contient pas de trace exploitable (moins de 2 points).")
        route = Route(
            route_id=new_route_id(), name=name or gpx_name or file.stem, source=f"gpx:{file.name}", points=points
        )
        if elevation == "dem":
            app.apply_dem(route)
        else:
            route.elevation_source = "fichier GPX"
        app.stats_into(route)
        app.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def import_official_trek(catalogue: Catalogue, trek_id: int, name: str | None = None) -> RouteSummary:
        """Importe le tracé officiel d'une rando (trouvée avec find_official_treks), puis recalcule distance,
        D+ et durée sur le MNT. Le D+ publié par le catalogue est comparé au nôtre (règle N5).
        Ensuite : set_constraints, analyze_route, export_route comme pour tout itinéraire.
        """
        if not app.services.geotrek:
            raise ToolError("Catalogues officiels non configurés.")
        if catalogue not in INSTANCES:
            raise ToolError(f"Catalogue inconnu : {catalogue} (champ `catalogue` de find_official_treks).")
        trek = app.external(lambda: app.services.geotrek.trek(catalogue, trek_id))
        route = Route(
            route_id=new_route_id(),
            name=name or trek.name,
            source=f"officiel:{catalogue}:{trek_id}",
            points=[TrackPoint(lat=la, lon=lo) for la, lo, _ in trek.coords],
            engine_stats={"distance_m": trek.length_km * 1000, "d_plus_m": trek.ascent_m},
        )
        app.apply_dem(route)
        app.stats_into(route)
        app.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def import_hiking_route(osm_id: str, name: str | None = None) -> RouteSummary:
        """Importe le tracé d'un **sentier balisé OpenStreetMap** (GR, PR, boucle locale…) trouvé avec
        find_hiking_routes (`osm_id` = « relation/123 »), puis calcule distance, D+ et durée sur le MNT.
        Si l'utilisateur nomme une rando balisée et qu'elle figure dans find_hiking_routes, l'importer ici plutôt
        que la reconstruire point par point. Ensuite : set_constraints, analyze_route, export_route.
        """
        m = re.fullmatch(r"(?:relation/)?(\d+)", osm_id.strip())
        if not m:
            raise ToolError("osm_id attendu : « relation/123 » (champ osm_id de find_hiking_routes).")
        rels = [
            e for e in app.overpass(f"[out:json][timeout:90];relation({m[1]});out geom;") if e.get("type") == "relation"
        ]
        if not rels:
            raise ToolError(f"Relation OSM {m[1]} introuvable.")
        rel = rels[0]
        try:
            coords, warnings = chain_route_relation(rel)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        tags = rel.get("tags", {})
        engine = declared_values(tags)
        route = Route(
            route_id=new_route_id(),
            name=name or tags.get("name") or tags.get("ref") or f"Sentier OSM {m[1]}",
            source=f"osm:relation/{m[1]}",
            points=[TrackPoint(lat=la, lon=lo) for la, lo in coords],
            engine_stats=engine,
        )
        if len(route.points) < 2:
            raise ToolError("Tracé trop court.")
        length_km = (
            cumulative_distance(np.array([la for la, _ in coords]), np.array([lo for _, lo in coords]))[-1] / 1000
        )
        if length_km > MAX_IMPORT_KM:
            raise ToolError(
                f"Sentier de {length_km:.0f} km : trop long pour un import d'un bloc (max {MAX_IMPORT_KM} km). "
                "Importer une étape (relation d'étape) ou tracer une portion avec route_between."
            )
        app.apply_dem(route)
        # Notes de source : conservées à chaque recalcul des stats (stats_into les reprend).
        route.elevation_notes = route.elevation_notes + warnings
        app.stats_into(route)
        app.save(route)
        return RouteSummary.of(route)

    @mcp.tool()
    def bailout_route(
        route_id: str,
        at_km: Annotated[float, Field(ge=0)],
        to: Literal["depart", "arrivee"] = "depart",
        target: LatLon | None = None,
        profile: Profile = "shortest",
    ) -> RouteSummary:
        """Itinéraire de repli : depuis le point situé à `at_km` sur le tracé, rejoindre au plus
        court le départ, l'arrivée, ou un lieu donné (`target` : parking, village, arrêt de bus).

        À proposer pour les passages exposés, la météo incertaine ou une fatigue imprévue.
        """
        route = app.load(route_id)
        if route.stats is None or at_km > route.stats.distance_km:
            raise ToolError(f"at_km doit être entre 0 et {route.stats.distance_km if route.stats else 0:.1f} km.")
        lats = np.array([p.lat for p in route.points])
        lons = np.array([p.lon for p in route.points])
        cum = cumulative_distance(lats, lons)
        here = (float(np.interp(at_km * 1000, cum, lats)), float(interp_lon(at_km * 1000, cum, lons)))
        if target:
            goal, label = (target.lat, target.lon), "le lieu choisi"
        else:
            p = route.points[0] if to == "depart" else route.points[-1]
            goal, label = (p.lat, p.lon), "le départ" if to == "depart" else "l'arrivée"
        bail = app.make_route(
            [here, goal],
            [here, goal],
            profile,
            RouteRequest(),
            f"Repli depuis le km {at_km:.1f} de « {route.name} » vers {label}",
        )
        app.save(bail)
        return RouteSummary.of(bail)
