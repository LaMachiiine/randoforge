"""Doublures des services externes : les tests ne touchent jamais le réseau.

Les réponses BRouter et Overpass (points notables) sont de vraies réponses enregistrées
(Lans-en-Vercors → Moucherotte, octobre 2026). Les autres réponses Overpass sont synthétiques,
choisies selon le contenu de la requête.
"""

import json
import math
from datetime import date
from pathlib import Path

import pytest

from randoforge.engines.brouter import parse_geojson
from randoforge.engines.elevation import ElevationResult
from randoforge.engines.osm import Place
from randoforge.server import Services, build_server
from randoforge.storage import RouteStore

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def route_geometry() -> list[dict]:
    coords = load_fixture("brouter_lans_moucherotte.json")["features"][0]["geometry"]["coordinates"]
    return [{"lat": c[1], "lon": c[0]} for c in coords]


class FakeRouter:
    def __init__(self):
        self.calls = []

    def route(self, waypoints, profile):
        self.calls.append((waypoints, profile))
        return parse_geojson(load_fixture("brouter_lans_moucherotte.json"))


class FakeElevation:
    """Relief analytique : monte vers le nord, avec une ondulation."""

    name = "Relief de test"

    def elevations(self, points):
        values = [1000 + (lat - 45.12) * 11_000 + 50 * math.sin(lon * 200) for lat, lon in points]
        return ElevationResult(values, [self.name] * len(points))


class FakeNominatim:
    def geocode(self, query, limit, country, near=None):
        return [Place(name=query, display_name=f"{query}, France", lat=45.1279, lon=5.5885, type="village")]


class FakeOverpass:
    """Répond selon la requête : zones, chemins, sentiers balisés, hébergements, sinon points notables."""

    def __init__(self):
        self.queries = []

    def query(self, ql):
        self.queries.append(ql)
        geom = route_geometry()
        if "national_park" in ql:
            # Parc national couvrant la seconde moitié du tracé (km ~4 → fin)
            lat0 = geom[len(geom) // 2]["lat"]
            ring = [(lat0, 5.5), (45.3, 5.5), (45.3, 5.8), (lat0, 5.8), (lat0, 5.5)]
            return [{"type": "way", "id": 900, "tags": {"boundary": "national_park", "name": "Parc de test"},
                     "geometry": [{"lat": a, "lon": b} for a, b in ring]}]  # fmt: skip
        if "way(around" in ql and '["highway"];out meta geom' in ql:
            return [{"type": "way", "id": 901, "tags": {"highway": "path"}, "timestamp": "2024-05-01T00:00:00Z",
                     "geometry": geom}]  # fmt: skip
        if 'route"="hiking' in ql:
            return [
                {"type": "relation", "id": 1, "tags": {"route": "hiking", "network": "lwn", "name": "Boucle locale"},
                 "center": {"lat": 45.13, "lon": 5.59}},
                {"type": "relation", "id": 2, "tags": {"route": "hiking", "network": "nwn", "ref": "GR 91",
                 "name": "Traversée du Vercors"}, "center": {"lat": 45.14, "lon": 5.6}},
                {"type": "relation", "id": 3, "tags": {"route": "hiking", "network": "lwn"}, "center": {"lat": 45.1, "lon": 5.5}},
            ]  # fmt: skip
        if "camp_site" in ql:
            mid = geom[len(geom) // 2]
            return [{"type": "node", "id": 902, "lat": mid["lat"], "lon": mid["lon"] + 0.0005,
                     "tags": {"tourism": "wilderness_hut", "name": "Cabane de test"}}]  # fmt: skip
        if "via_ferrata" in ql:
            return []
        return load_fixture("overpass_lans_moucherotte.json")


class FakeRefuges:
    def points(self, s, w, n, e):
        geom = route_geometry()
        q = geom[len(geom) // 4]
        return [
            {"id": 1, "nom": "Refuge de test", "type": "refuge gardé", "lat": q["lat"], "lon": q["lon"], "alt": 1200,
             "places": 20, "lien": "https://www.refuges.info/point/1"},
            {"id": 2, "nom": "Source", "type": "point d'eau", "lat": q["lat"], "lon": q["lon"], "alt": 1200,
             "places": None, "lien": None},
        ]  # fmt: skip


class FakeWeather:
    def __init__(self, storm: bool = False):
        self.storm = storm

    def hourly(self, lat, lon, elevation, day):
        hours = [f"{day.isoformat()}T{h:02d}:00" for h in range(24)]
        return {"hourly": {"time": hours, "temperature_2m": [12 - (elevation or 0) / 300] * 24, "precipitation": [0.5] * 24,
                           "weather_code": [95 if self.storm and h == 15 else 1 for h in range(24)],
                           "wind_gusts_10m": [30] * 24, "snow_depth": [0] * 24, "cape": [100] * 24}}  # fmt: skip


class FakeGeotrek:
    """Catalogue officiel : une rando dont le tracé est la vraie géométrie BRouter enregistrée."""

    def search(self, instance, query=None, bbox=None, limit=20):
        from randoforge.engines.geotrek import OfficialTrek

        if instance != "ecrins":
            return []
        return [OfficialTrek(parc="ecrins", trek_id=1, nom="Montée au Moucherotte", depart="Lans-en-Vercors",
                             arrivee="Moucherotte", type="Aller-retour", distance_km=7.6, d_plus_m=700,
                             resume="Rando de test", depart_lat=45.1279, depart_lon=5.5885)]  # fmt: skip

    def trek(self, instance, trek_id):
        from randoforge.engines.geotrek import ReferenceTrek

        return ReferenceTrek(source=instance, id=trek_id, name="Montée au Moucherotte", ascent_m=700, descent_m=0,
                             length_km=7.585, min_elevation_m=None, max_elevation_m=None,
                             coords=[(p["lat"], p["lon"], None) for p in route_geometry()])  # fmt: skip


class FakeWikidata:
    def describe(self, ids, lang="fr"):
        return {
            i: {"description": f"description de {i}", "wikipedia": f"https://fr.wikipedia.org/wiki/{i}"} for i in ids
        }


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def store(tmp_path):
    return RouteStore(tmp_path)


@pytest.fixture
def services():
    return Services(router=FakeRouter(), elevation=FakeElevation(), nominatim=FakeNominatim(), overpass=FakeOverpass(),
                    refuges=FakeRefuges(), weather=FakeWeather(), wikidata=FakeWikidata(), geotrek=FakeGeotrek())  # fmt: skip


@pytest.fixture
def server(store, services):
    return build_server(store, services)


@pytest.fixture
def soon():
    return date.today()
