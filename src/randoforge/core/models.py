"""Modèles de données partagés : points, paramètres de calcul, statistiques, itinéraire."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class TrackPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    ele: float | None = None


class ElevationParams(BaseModel):
    """Paramètres du pipeline D+/D- (voir docs/10 - Architecture/Calcul du dénivelé.md)."""

    step_m: float = Field(10.0, gt=0, le=100, description="Pas de rééchantillonnage le long du tracé")
    smooth_window_m: float = Field(
        30.0, ge=0, le=500, description="Fenêtre du filtre médian (0 = pas de lissage)"
    )
    threshold_m: float = Field(
        5.0, ge=0, le=50, description="Seuil d'hystérésis avant de compter une montée/descente"
    )


class WalkerProfile(BaseModel):
    """Vitesses du marcheur, utilisées par la méthode DIN 33466."""

    flat_kmh: float = Field(4.0, gt=0, le=10)
    up_m_per_h: float = Field(300.0, gt=0, le=1500)
    down_m_per_h: float = Field(500.0, gt=0, le=2000)


class RouteStats(BaseModel):
    distance_km: float
    d_plus_m: float | None
    d_minus_m: float | None
    alt_min_m: float | None
    alt_max_m: float | None
    duration_min: int | None
    duration_label: str | None
    is_loop: bool
    elevation_source: str
    params: ElevationParams
    profile: WalkerProfile


class Route(BaseModel):
    route_id: str
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str
    points: list[TrackPoint]
    stats: RouteStats | None = None
    warnings: list[str] = Field(default_factory=list)


class RouteSummary(BaseModel):
    """Vue compacte d'un itinéraire, renvoyée à Claude (sans la géométrie)."""

    route_id: str
    name: str
    source: str
    n_points: int
    stats: RouteStats | None
    warnings: list[str]

    @classmethod
    def of(cls, route: Route) -> RouteSummary:
        return cls(
            route_id=route.route_id,
            name=route.name,
            source=route.source,
            n_points=len(route.points),
            stats=route.stats,
            warnings=route.warnings,
        )
