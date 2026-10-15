"""Doublures des services externes : les tests ne touchent jamais le réseau.

Les réponses BRouter et Overpass sont de vraies réponses enregistrées
(Lans-en-Vercors → Moucherotte, octobre 2026).
"""

import json
import math
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


class FakeRouter:
    def __init__(self):
        self.calls = []

    def route(self, waypoints, profile):
        self.calls.append((waypoints, profile))
        return parse_geojson(load_fixture("brouter_lans_moucherotte.json"))


class FakeElevation:
    """Relief analytique : monte de 1000 m vers le nord-est (≈ 100 m par km vers le nord)."""

    name = "Relief de test"

    def elevations(self, points):
        values = [1000 + (lat - 45.12) * 11_000 + 50 * math.sin(lon * 200) for lat, lon in points]
        return ElevationResult(values, [self.name] * len(points))


class FakeNominatim:
    def geocode(self, query, limit, country):
        return [Place(name=query, display_name=f"{query}, France", lat=45.1279, lon=5.5885, type="village")]


class FakeOverpass:
    def __init__(self):
        self.queries = []

    def query(self, ql):
        self.queries.append(ql)
        return load_fixture("overpass_lans_moucherotte.json")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def store(tmp_path):
    return RouteStore(tmp_path)


@pytest.fixture
def services():
    return Services(router=FakeRouter(), elevation=FakeElevation(), nominatim=FakeNominatim(), overpass=FakeOverpass())


@pytest.fixture
def server(store, services):
    return build_server(store, services)
