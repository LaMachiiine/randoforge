"""Interfaces des moteurs externes. Les implémentations arrivent en phase 1.

- RoutingEngine : BRouter, GraphHopper… (voir docs/20 - Plan/Décisions/ADR-002)
- ElevationProvider : IGN RGE ALTI en France, Copernicus GLO-30 ailleurs (ADR-003)
"""

from __future__ import annotations

from typing import Protocol

from ..core.models import TrackPoint


class RoutingEngine(Protocol):
    name: str

    def route(self, waypoints: list[tuple[float, float]], profile: str) -> list[TrackPoint]:
        """Tracé passant par les waypoints (lat, lon), sur le réseau de chemins."""
        ...


class ElevationProvider(Protocol):
    name: str

    def covers(self, lat: float, lon: float) -> bool:
        """Vrai si le fournisseur a des données pour ce point."""
        ...

    def elevations(self, points: list[tuple[float, float]]) -> list[float | None]:
        """Altitude (m) de chaque point (lat, lon) ; None si indisponible."""
        ...
