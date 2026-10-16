"""Modèles de données partagés : points, paramètres de calcul, statistiques, itinéraire."""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as Date
from datetime import time as Time

from pydantic import BaseModel, Field, model_serializer

NOT_VALIDATED = "Lancer analyze_route (ou validate_route) avant de présenter cet itinéraire."


class Compact(BaseModel):
    """Modèle renvoyé à Claude : les champs vides (None, False, listes vides) sont omis pour économiser
    des jetons. Les zéros sont conservés (km 0, D+ 0 sont des informations)."""

    @model_serializer(mode="wrap")
    def _drop_empty(self, handler):
        data = handler(self)
        fields = type(self).model_fields
        # Seuls les champs facultatifs peuvent disparaître : le schéma de sortie exige les autres.
        return {
            k: v
            for k, v in data.items()
            if (k in fields and fields[k].is_required()) or (v is not None and v is not False and v != [] and v != {})
        }


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
    d_plus_fourchette_m: tuple[int, int] | None = Field(
        None, description="D+ plausible (bas, haut) : la référence officielle y tombe 4 fois sur 5 (calibration)"
    )
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


class Poi(Compact):
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
    description: str | None = Field(None, description="Description Wikidata, si disponible")
    wikipedia_url: str | None = None
    osm_id: str


class TechnicalPassage(Compact):
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
    target_distance_km: float | None = None
    target_d_plus_m: float | None = None
    max_duration_h: float | None = None
    date: Date | None = None
    start_time: Time | None = None
    with_dog: bool = False
    with_children: bool = False
    stroller: bool = False


class AreaCrossing(Compact):
    """Zone réglementée traversée (parc national, réserve, terrain militaire…)."""

    nom: str | None
    kind: str = Field(
        description="parc national, réserve naturelle, parc naturel régional, zone protégée, zone militaire"
    )
    protect_class: str | None = None
    km_debut: float
    km_fin: float
    chiens: str | None = Field(None, description="interdits, en laisse, autorisés ou None si inconnu")
    bivouac: str | None = Field(None, description="interdit, réglementé ou None si inconnu")
    notes: list[str] = Field(default_factory=list)
    osm_id: str


class BivouacSpot(Compact):
    km: float
    abrite: bool = Field(False, description="Toit ou paroi : refuge, cabane, abri, grotte, abri sous roche")
    lat: float
    lon: float
    source: str = Field(description="OSM, refuges.info ou calculé")
    type: str
    nom: str | None = None
    detour_m: float = 0
    alt: float | None = None
    pente_pct: float | None = Field(None, description="Pente max mesurée sur ±15 m (emplacements calculés)")
    eau_m: float | None = Field(None, description="Distance au point d'eau connu le plus proche")
    places: int | None = None
    lien: str | None = None
    score: float = 0
    avertissements: list[str] = Field(default_factory=list)


class Stage(Compact):
    jour: int
    km_debut: float
    km_fin: float
    distance_km: float
    d_plus_m: int
    d_minus_m: int
    duree_min: int
    duree: str
    arrivee: str = Field(description="Hébergement ou point d'arrivée de l'étape")
    arrivee_type: str
    passages_techniques: list[str] = Field(default_factory=list)
    points_eau: int = 0


class WeatherWindow(BaseModel):
    lieu: str
    altitude_m: float
    temp_min_c: float | None
    temp_max_c: float | None
    pluie_mm: float | None
    rafales_max_kmh: float | None
    neige_m: float | None
    orage: bool


class WeatherReport(BaseModel):
    date: Date
    heures: str
    points: list[WeatherWindow]
    alertes: list[str]
    source: str = "Open-Meteo"
    validation_status: str | None = Field(
        None, description="Statut de la validation de l'itinéraire (faite automatiquement)"
    )
    alertes_itineraire: list[str] = Field(
        default_factory=list, description="Erreurs et avertissements de la validation"
    )
    analyses_indisponibles: list[str] = Field(
        default_factory=list, description="Vérifications impossibles (service indisponible) : statut incomplet"
    )


class SnowReport(Compact):
    """Enneigement le long du tracé : observations satellite, limite de la neige, modèle et durée ajustée."""

    applicable: bool = Field(description="Faux hors saison froide / altitude : rien n'a été analysé")
    message: str = Field(description="Résumé en une phrase")
    date: Date
    limite_neige_m: int | None = Field(None, description="Altitude au-dessus de laquelle le sol est enneigé")
    limite_source: str | None = None
    part_enneigee_pct: float | None = Field(None, description="Part du tracé probablement enneigée")
    troncons_enneiges: list[str] = Field(default_factory=list, description="Tronçons enneigés (km) et facteur")
    vu_par_satellite_pct: float | None = Field(None, description="Part du tracé observée sans nuage")
    sentinel2: str | None = Field(None, description="Image Sentinel-2 (20 m) utilisée, si récente")
    epaisseur_modele_cm: tuple[int, int] | None = Field(None, description="Épaisseur modélisée (min, max), estimation")
    neige_fraiche_72h_cm: float | None = Field(None, description="Neige tombée sur 3 jours (modèle)")
    en_raquettes: bool = False
    duree_normale: str | None = None
    duree_neige: str | None = Field(None, description="Durée ajustée à la neige (estimation ≈)")
    sources: list[str] = Field(default_factory=list)
    avertissements: list[str] = Field(default_factory=list)


class AvalancheReport(Compact):
    """Terrain avalancheux le long du tracé, d'après le relief (pas un bulletin de risque)."""

    message: str
    troncons: list[str] = Field(default_factory=list, description="Tronçons exposés (km), pente et hauteur")
    part_exposee_pct: float = Field(description="Part du tracé sur ou sous une pente de départ possible")
    pente_max_traversee_deg: float | None = None
    source: str
    avertissements: list[str] = Field(default_factory=list)


class TransitLine(Compact):
    ligne: str
    direction: str
    horaires: list[str] = Field(description="Heures de passage (heure locale)")


class TransitSide(Compact):
    arrets: list[str] = Field(default_factory=list, description="Arrêts desservis à proximité (distance)")
    lignes: list[TransitLine] = Field(default_factory=list)
    premier_retour: str | None = Field(None, description="Premier passage après l'arrivée estimée")


class TransitReport(Compact):
    """Transports en commun au départ et à l'arrivée, le jour de la sortie (horaires théoriques)."""

    message: str
    date: Date
    depart: TransitSide | None = None
    arrivee: TransitSide | None = Field(None, description="Absente pour une boucle (même arrêts qu'au départ)")
    arrivee_estimee: str | None = Field(None, description="Heure d'arrivée estimée (pauses comprises)")
    source: str


class WaterHutPoint(Compact):
    km: float
    type: str
    nom: str
    distance_m: float = Field(description="Distance au tracé")
    etat: str | None = Field(None, description="État signalé (tari, intermittent, fermée, détruite…)")
    equipement: str | None = None
    derniers_avis: list[str] = Field(default_factory=list, description="Commentaires datés des visiteurs")
    lien: str | None = None


class WaterHutsReport(Compact):
    """Points d'eau, cabanes et refuges près du tracé, avec leur état et les derniers avis (refuges.info)."""

    message: str
    points: list[WaterHutPoint]
    source: str = "© Les contributeurs de Refuges.info (CC BY-SA), commentaires de leurs auteurs"
    avertissements: list[str] = Field(default_factory=list)


class MobileCoverageReport(Compact):
    """Couverture mobile théorique le long du tracé (France, Arcep)."""

    message: str
    reseau_pct: float | None = Field(
        None, description="Part du tracé avec réseau (voix 2G/3G ou 4G), au moins un opérateur"
    )
    voix_pct: float | None = Field(None, description="Part du tracé où au moins un opérateur passe en voix 2G/3G")
    voix_bonne_pct: float | None = Field(None, description="Idem, en bonne ou très bonne couverture")
    donnees_4g_pct: float | None = None
    zones_sans_reseau: list[str] = Field(default_factory=list, description="Tronçons sans voix ni 4G (km)")
    par_operateur: dict[str, float] = Field(
        default_factory=dict, description="Part couverte en voix 2G/3G par opérateur"
    )
    source: str
    avertissements: list[str] = Field(default_factory=list)


class Quality(BaseModel):
    score: float = Field(description="Confiance dans les données, de 0 à 1")
    niveau: str
    raisons: list[str]
    sur_chemin_pct: float | None = None
    hors_chemin: list[tuple[float, float]] = Field(default_factory=list, description="Portions hors chemin (km)")
    annee_mediane_edition: int | None = None


class Check(Compact):
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
    areas: list[AreaCrossing] | None = None
    bivouacs: list[BivouacSpot] | None = None
    stages: list[Stage] | None = None
    weather: WeatherReport | None = None
    snow: SnowReport | None = None
    avalanche: AvalancheReport | None = None
    quality: Quality | None = None
    done_on: Date | None = None
    done_notes: str | None = None


class StatsSummary(Compact):
    """Statistiques utiles à Claude (sans les paramètres de calcul, disponibles dans les exports)."""

    distance_km: float
    d_plus_m: int | None
    d_plus_fourchette_m: tuple[int, int] | None = Field(
        None, description="D+ plausible (bas, haut) : la référence officielle y tombe 4 fois sur 5 (calibration)"
    )
    d_minus_m: int | None
    alt_min_m: int | None
    alt_max_m: int | None
    duration_min: int | None
    duration_label: str | None
    is_loop: bool
    elevation_source: str

    @classmethod
    def of(cls, s: RouteStats | None) -> StatsSummary | None:
        return cls(**s.model_dump(exclude={"params", "profile"})) if s else None


class RouteSummary(Compact):
    """Vue compacte d'un itinéraire, renvoyée à Claude (sans la géométrie)."""

    route_id: str
    name: str
    source: str
    stats: StatsSummary | None
    warnings: list[str] = Field(default_factory=list)
    validation_status: str | None = None
    n_pois: int | None = None
    prochaine_etape: str | None = Field(None, description="Rappel tant que l'itinéraire n'est pas validé")

    @classmethod
    def of(cls, route: Route) -> RouteSummary:
        return cls(
            route_id=route.route_id,
            name=route.name,
            source=route.source,
            stats=StatsSummary.of(route.stats),
            warnings=route.warnings,
            validation_status=route.validation.status if route.validation else None,
            prochaine_etape=None if route.validation else NOT_VALIDATED,
            n_pois=len(route.pois) if route.pois is not None else None,
        )
