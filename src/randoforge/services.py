"""Dépendances externes du serveur, injectables (les tests fournissent des doublures)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .engines.brouter import BRouterEngine
from .engines.elevation import CopernicusElevation, ElevationChain, IgnElevation, LocalDemElevation
from .engines.extra import OpenMeteo, RefugesInfo, Wikidata
from .engines.osm import Nominatim, Overpass
from .http import CachedHttp


@dataclass
class Services:
    router: object
    elevation: object
    nominatim: object
    overpass: object
    refuges: object | None = None
    weather: object | None = None
    wikidata: object | None = None

    @classmethod
    def from_env(cls, home: Path) -> Services:
        """Services réels, configurables par variables d'environnement :
        RANDOFORGE_BROUTER_URL, RANDOFORGE_OVERPASS_URLS (liste séparée par des virgules),
        RANDOFORGE_DEM_DIR (dossier de GeoTIFF prioritaires)."""
        http = CachedHttp(home / "cache.sqlite")
        overpass_urls = [u for u in os.environ.get("RANDOFORGE_OVERPASS_URLS", "").split(",") if u]
        providers: list = [IgnElevation(http), CopernicusElevation()]
        if dem_dir := os.environ.get("RANDOFORGE_DEM_DIR"):
            providers.insert(0, LocalDemElevation(Path(dem_dir)))
        return cls(
            router=BRouterEngine(http, os.environ.get("RANDOFORGE_BROUTER_URL", "https://brouter.de/brouter")),
            elevation=ElevationChain(providers),
            nominatim=Nominatim(http),
            overpass=Overpass(http, overpass_urls or None),
            refuges=RefugesInfo(http),
            weather=OpenMeteo(http),
            wikidata=Wikidata(http),
        )
