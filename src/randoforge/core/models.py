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
    smooth_window_m: float = Field(30.0, ge=0, le=500, description="Fenêtre du filtre médian (0 = pas de lissage)")
    threshold_m: float = Field(5.0, ge=0, le=50, description="Seuil d'hystérésis avant de compter une montée/descente")


class WalkerProfile(BaseModel):
    """Vitesses du marcheur, utilisées par la méthode DIN 33466."""

    flat_kmh: float = Field(4.0, gt=0, le=10)
    up_m_per_h: float = Field(300.0, gt=0, le=1500)
    down_m_per_h: float = Field(500.0, gt=0, le=2000)


class RouteStats(BaseModel):
    distance_km: float
    d_plus_m: int | None
    d_minus_m: int | None
    alt_min_m: int | None
    alt_max_m: int | None
    duration_min: int | None
    duration_label: str | None
    is_loop: bool
    elevation_source: str
    params: ElevationParams
    profile: WalkerProfile


SAC_SCALE = [
    "hiking",
    "mountain_hiking",
    "demanding_mountain_hiking",
    "alpine_hiking",
    "demanding_alpine_hiking",
    "difficult_alpine_hiking",
]
"""Échelle de difficulté OSM (CAS T1 → T6), dans l'ordre croissant."""


class WaySegment(BaseModel):
    """Portion du tracé sur un même chemin OSM, avec ses tags (fournis par le moteur de routage)."""

    start_m: float
    end_m: float
    tags: dict[str, str]


class Poi(BaseModel):
    """Point notable situé sur le tracé ou à proximité."""

    km: float = Field(description="Position le long du tracé")
    categorie: str
    type: str = Field(description="Valeur du tag OSM principal (waterfall, viewpoint…)")
    nom: str | None = None
    lat: float
    lon: float
    distance_m: float = Field(description="Distance au tracé")
    detour_m: float = Field(description="Détour aller-retour estimé (0 si sur le tracé)")
    score: float = Field(description="Intérêt indicatif entre 0 et 1")
    ele: float | None = None
    via: str | None = Field(None, description="Franchissement : 'gué' si un gué est cartographié")
    intermittent: bool = False
    wikidata: str | None = None
    wikipedia: str | None = None
    osm_id: str


class TechnicalPassage(BaseModel):
    km: float
    longueur_m: float
    niveau: str | None = Field(description="Niveau max sur l'échelle T1–T6 si renseigné dans OSM")
    types: list[str]
    details: list[str]
    sources: list[str]
    a_verifier: bool = Field(False, description="Indice possiblement erroné (ex. artefact du MNT)")


class RouteRequest(BaseModel):
    """Contraintes demandées, vérifiées par la validation."""

    loop: bool = False
    max_sac_scale: str | None = None
    max_tarmac_pct: float = 30.0


class Check(BaseModel):
    id: str
    level: str = Field(description="error, warning ou info")
    message: str
    km: float | None = None
    suggestion: str | None = None


class ValidationReport(BaseModel):
    status: str = Field(description="ok, warning ou error")
    checks: list[Check]


class Route(BaseModel):
    route_id: str
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str
    points: list[TrackPoint]
    waypoints: list[tuple[float, float]] = Field(default_factory=list)
    request: RouteRequest = Field(default_factory=RouteRequest)
    segments: list[WaySegment] = Field(default_factory=list)
    engine_stats: dict[str, float] = Field(default_factory=dict)
    elevation_source: str = "inconnue"
    elevation_notes: list[str] = Field(default_factory=list, description="Avertissements liés aux altitudes")
    stats: RouteStats | None = None
    warnings: list[str] = Field(default_factory=list)
    pois: list[Poi] | None = None
    technical: list[TechnicalPassage] | None = None
    validation: ValidationReport | None = None


class RouteSummary(BaseModel):
    """Vue compacte d'un itinéraire, renvoyée à Claude (sans la géométrie)."""

    route_id: str
    name: str
    source: str
    n_points: int
    stats: RouteStats | None
    warnings: list[str]
    validation_status: str | None = None
    n_pois: int | None = None

    @classmethod
    def of(cls, route: Route) -> RouteSummary:
        return cls(
            route_id=route.route_id,
            name=route.name,
            source=route.source,
            n_points=len(route.points),
            stats=route.stats,
            warnings=route.warnings,
            validation_status=route.validation.status if route.validation else None,
            n_pois=len(route.pois) if route.pois is not None else None,
        )
