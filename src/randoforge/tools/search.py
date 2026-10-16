"""Outils de recherche : lieux, points notables, sentiers balisés."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..app import DEFAULT_CATEGORIES, App
from ..core import pois as poi_lib
from ..core.geo import distance_m
from ..core.models import TrackPoint
from ..engines.geotrek import INSTANCES
from .schemas import (
    CategoryName,
    HikingRoute,
    HikingRouteList,
    LatLon,
    OfficialTrekList,
    Park,
    PlaceList,
    PoiNearby,
    PoiSearchResult,
)

NETWORKS = {"iwn": "international", "nwn": "national", "rwn": "régional", "lwn": "local"}


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def geocode(
        query: str,
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
        country: str | None = None,
        near: LatLon | None = None,
    ) -> PlaceList:
        """Trouve les coordonnées d'un lieu (village, sommet, parking, lac…) par son nom.

        `country` : code ISO à 2 lettres (fr, ch, it…). `near` : privilégie les résultats proches d'un point
        (ex. le village de départ) — utile pour un sommet homonyme d'une rue ou d'un bâtiment. Pour un sommet,
        un col ou une cascade, find_pois autour du départ est souvent plus sûr.
        """
        around = (near.lat, near.lon) if near else None
        return PlaceList(places=app.external(lambda: app.services.nominatim.geocode(query, limit, country, around)))

    @mcp.tool()
    def find_pois(
        lat: float,
        lon: float,
        radius_km: Annotated[float, Field(gt=0, le=15)] = 3.0,
        categories: list[CategoryName] | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 30,
    ) -> PoiSearchResult:
        """Cherche des points notables autour d'un lieu pour planifier un itinéraire :
        cascades, points de vue, lacs, sommets et cols, curiosités, patrimoine, eau, refuges…
        Ajouter la catégorie `transport` pour les arrêts de bus et gares (départ sans voiture).

        Résultats triés par intérêt. Seuls les lieux cartographiés dans OpenStreetMap apparaissent.
        """
        cats = list(categories or DEFAULT_CATEGORIES)
        radius_m = radius_km * 1000
        bbox = poi_lib.bbox_around([TrackPoint(lat=lat, lon=lon)], radius_m)
        elements = app.overpass(poi_lib.build_query(bbox, cats))
        found = poi_lib.near_point(lat, lon, elements, cats, radius_m)
        return PoiSearchResult(
            pois=[PoiNearby(poi=p, distance_from_center_m=round(d)) for p, d in found[:limit]],
            truncated=len(found) > limit,
        )

    @mcp.tool()
    def find_official_treks(
        query: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: Annotated[float, Field(gt=0, le=30)] = 10.0,
        parc: Park | None = None,
        limit: Annotated[int, Field(ge=1, le=30)] = 10,
    ) -> OfficialTrekList:
        """Randos **officielles** des parcs nationaux (Écrins, Cévennes, Port-Cros) : par nom (`query`) et/ou
        autour d'un lieu. Si l'utilisateur nomme une rando de parc ou veut une rando « balisée et décrite » dans
        un de ces parcs, chercher ici d'abord puis l'importer avec import_official_trek plutôt que la reconstruire.
        """
        if not app.services.geotrek:
            raise ToolError("Catalogue des parcs non configuré.")
        if not query and (lat is None or lon is None):
            raise ToolError("Donner un nom (query) et/ou un lieu (lat, lon).")
        bbox = None
        if lat is not None and lon is not None:
            bbox = poi_lib.bbox_around([TrackPoint(lat=lat, lon=lon)], radius_km * 1000)
        parks = [parc] if parc else list(INSTANCES)
        res = app.parallel({p: (lambda p=p: app.external(lambda: app.services.geotrek.search(p, query, bbox, limit)))
                            for p in parks})  # fmt: skip
        treks = [t for r in res.values() if isinstance(r, list) for t in r]
        if lat is not None and lon is not None:
            treks.sort(key=lambda t: distance_m((lat, lon), (t.depart_lat, t.depart_lon)) if t.depart_lat else 1e9)
        if not treks and all(isinstance(r, ToolError) for r in res.values()):
            raise ToolError("Catalogues des parcs indisponibles : " + " ; ".join(str(r) for r in res.values()))
        return OfficialTrekList(treks=treks[:limit])

    @mcp.tool()
    def find_hiking_routes(
        lat: float,
        lon: float,
        radius_km: Annotated[float, Field(gt=0, le=20)] = 5.0,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> HikingRouteList:
        """Sentiers balisés (GR, GRP, PR, sentiers locaux) qui passent à proximité d'un lieu,
        des plus importants (réseau international/national) aux plus locaux.

        Utile pour proposer un itinéraire balisé ; pour tracer une portion, utiliser route_between
        avec des points situés sur le sentier.
        """
        q = f'[out:json][timeout:90];relation["route"="hiking"](around:{radius_km * 1000:.0f},{lat},{lon});out tags center;'
        rels = app.overpass(q)
        order = list(NETWORKS)
        rows = []
        for r in rels:
            t = r.get("tags", {})
            if not t.get("name") and not t.get("ref"):
                continue  # relation anonyme : inutilisable pour décrire un itinéraire
            dist = None
            try:
                dist = float(t.get("distance", "").replace(",", ".").split()[0])
            except (ValueError, IndexError):
                pass
            rows.append(
                (
                    order.index(t["network"]) if t.get("network") in order else len(order),
                    distance_m((lat, lon), (r["center"]["lat"], r["center"]["lon"])) if r.get("center") else 0,
                    HikingRoute(
                        nom=t.get("name"),
                        ref=t.get("ref"),
                        reseau=NETWORKS.get(t.get("network", ""), "inconnu"),
                        distance_km=dist,
                        balisage=t.get("osmc:symbol"),
                        wikipedia=t.get("wikipedia"),
                        osm_id=f"relation/{r['id']}",
                    ),
                )
            )
        rows.sort(key=lambda x: (x[0], x[1]))
        return HikingRouteList(routes=[r for _, _, r in rows[:limit]])
