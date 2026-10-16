"""Types d'entrée et de sortie des outils MCP."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from ..core.models import (
    AreaCrossing,
    BivouacSpot,
    Poi,
    Quality,
    RouteSummary,
    Stage,
    TechnicalPassage,
    ValidationReport,
    WalkerProfile,
)
from ..core.similarity import ReferenceComparison
from ..engines.geotrek import OfficialTrek
from ..engines.osm import Place

Catalogue = Annotated[
    str, Field(description="Identifiant de catalogue officiel (champ `catalogue` de find_official_treks)")
]
CategoryName = Literal[
    "cascade", "point_de_vue", "lac", "sommet", "curiosite", "riviere", "patrimoine", "eau", "pause", "transport"
]
SacScale = Literal["hiking", "mountain_hiking", "demanding_mountain_hiking", "alpine_hiking", "demanding_alpine_hiking"]
Profile = Literal["hiking-mountain", "hiking-beta", "shortest"]
Walker = Literal["famille", "moyen", "sportif"]
WALKERS = {
    "famille": WalkerProfile(flat_kmh=3.0, up_m_per_h=200, down_m_per_h=350),
    "moyen": WalkerProfile(),
    "sportif": WalkerProfile(flat_kmh=5.0, up_m_per_h=450, down_m_per_h=700),
}


class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class PlaceList(BaseModel):
    places: list[Place]


class PoiNearby(BaseModel):
    poi: Poi
    distance_from_center_m: float


class PoiSearchResult(BaseModel):
    pois: list[PoiNearby]
    truncated: bool
    source: str = "OpenStreetMap (Overpass)"


class HikingRoute(BaseModel):
    nom: str | None
    ref: str | None
    reseau: str = Field(description="international, national, régional ou local")
    distance_km: float | None = Field(None, description="Longueur déclarée dans OSM, si renseignée")
    balisage: str | None = Field(None, description="Symbole osmc:symbol")
    wikipedia: str | None = None
    osm_id: str


class OfficialTrekList(BaseModel):
    treks: list[OfficialTrek]
    catalogues: dict[str, str] = Field(default_factory=dict, description="Nom de chaque catalogue cité")
    source: str = "Catalogues officiels Geotrek (parcs, départements, intercommunalités) : tracés des topo-guides"


class HikingRouteList(BaseModel):
    routes: list[HikingRoute]
    source: str = "OpenStreetMap (relations route=hiking)"


class AnnotationResult(BaseModel):
    route_id: str
    pois: list[Poi] = Field(description="Les plus intéressants, triés par km (liste complète dans les exports)")
    total: int = Field(description="Nombre total de points notables trouvés")
    warnings: list[str]
    source: str = "OpenStreetMap (Overpass), descriptions Wikidata"


class AnalysisResult(BaseModel):
    """Analyse complète en un appel (économise des tours d'agent et des jetons)."""

    route_id: str
    validation: ValidationReport
    pois: list[Poi] = Field(description="Points notables les plus intéressants, triés par km")
    pois_total: int
    passages_techniques: list[TechnicalPassage]
    zones: list[AreaCrossing]
    indisponible: list[str] = Field(default_factory=list, description="Analyses qui n'ont pas pu être faites")


class TechnicalResult(BaseModel):
    route_id: str
    passages: list[TechnicalPassage]
    niveau_max: str | None
    notes: list[str]


class AreasResult(BaseModel):
    route_id: str
    zones: list[AreaCrossing]
    notes: list[str]


class QualityResult(BaseModel):
    route_id: str
    qualite: Quality
    balise_pct: float | None


class LoopCandidate(BaseModel):
    route: RouteSummary
    bearing_deg: float = Field(description="Direction générale de la boucle depuis le départ (0 = nord)")
    retrace_km: float = Field(description="Distance parcourue deux fois (aller-retour)")
    tarmac_pct: float
    balise_pct: float | None = Field(None, description="Part sur sentiers balisés (GR, PR…)")
    deja_fait_pct: float = Field(0, description="Part commune avec des randos déjà faites")
    score: float = Field(description="Plus petit = plus proche de la demande")


class ResolvedPlace(BaseModel):
    lieu: str = Field(description="Lieu tel que cité")
    trouve: str = Field(description="Lieu retenu sur la carte (nom OSM)")
    lat: float
    lon: float
    km_du_depart: float = Field(description="Distance à vol d'oiseau depuis le départ")


class PlacesRoute(BaseModel):
    route: RouteSummary
    lieux: list[ResolvedPlace]
    non_trouves: list[str] = Field(default_factory=list, description="Lieux introuvables près du départ, ignorés")
    douteux: list[str] = Field(
        default_factory=list, description="Lieux trouvés seulement loin du parcours (homonymes ?), ignorés"
    )


class LoopCandidates(BaseModel):
    candidates: list[LoopCandidate]
    tried: int
    failed: int
    notes: list[str]


class ComparisonRow(BaseModel):
    route_id: str
    name: str
    distance_km: float | None
    d_plus_m: int | None
    duree: str | None
    alt_max_m: int | None
    tarmac_pct: float | None
    balise_pct: float | None
    retrace_km: float
    deja_fait_pct: float
    niveau_technique_max: str | None
    n_passages_techniques: int | None
    n_pois: int | None
    validation: str | None


class Comparison(BaseModel):
    rows: list[ComparisonRow]


class ReferenceResult(BaseModel):
    route_id: str
    reference_id: str
    comparaison: ReferenceComparison


class BivouacResult(BaseModel):
    route_id: str
    emplacements: list[BivouacSpot] = Field(description="Les meilleurs, triés par km (tous servent à plan_stages)")
    total: int
    rappels: list[str] = Field(description="Avertissements communs à tous les emplacements, donnés une seule fois")


class StagesResult(BaseModel):
    route_id: str
    etapes: list[Stage]
    notes: list[str]


class RouteList(BaseModel):
    routes: list[RouteSummary]


class ExportResult(BaseModel):
    route_id: str
    files: dict[str, str]
