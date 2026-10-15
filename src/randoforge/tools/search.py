"""Outils de recherche : lieux, points notables, sentiers balisés."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from ..app import DEFAULT_CATEGORIES, App
from ..core import pois as poi_lib
from ..core.geo import distance_m
from ..core.models import TrackPoint
from .schemas import CategoryName, HikingRoute, HikingRouteList, PlaceList, PoiNearby, PoiSearchResult

NETWORKS = {"iwn": "international", "nwn": "national", "rwn": "régional", "lwn": "local"}


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def geocode(query: str, limit: Annotated[int, Field(ge=1, le=10)] = 5, country: str | None = None) -> PlaceList:
        """Trouve les coordonnées d'un lieu (village, sommet, parking, lac…) par son nom.

        `country` : code ISO à 2 lettres (fr, ch, it…) pour lever les ambiguïtés.
        """
        return PlaceList(places=app.external(lambda: app.services.nominatim.geocode(query, limit, country)))

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
