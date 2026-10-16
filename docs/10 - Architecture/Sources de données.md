---
tags: [architecture, donnees]
---
# Sources de données

> ⚠️ À vérifier : quotas, licences et URL exactes au moment de l'implémentation.

## Réseau de chemins — OpenStreetMap
| Usage | Outil | Notes |
|---|---|---|
| Requêtes de chemins, POI | **Overpass API** | Gratuit, quotas ; mettre en cache. Instance perso possible |
| Géocodage | **Nominatim** / **Photon** | 1 req/s sur Nominatim public |
| Sentiers balisés (GR, PR) | Relations `route=hiking` | Cf. Waymarked Trails |

### Tags OSM utiles
- `highway=path|footway|track|steps` — type de voie
- `sac_scale=hiking|mountain_hiking|demanding_mountain_hiking|alpine_hiking…` — difficulté (échelle CAS)
- `trail_visibility`, `surface`, `tracktype`
- `access=no|private`, `foot=no` — **interdictions à respecter**
- `natural=peak` (+ `ele`), `natural=water`, `tourism=viewpoint`, `amenity=drinking_water`, `tourism=alpine_hut`
- `boundary=national_park|protected_area` — réglementations

## Altimétrie (MNT)
| Source | Résolution | Couverture | Usage |
|---|---|---|---|
| **IGN RGE ALTI** (via API Altimétrie Géoplateforme) | 1–5 m | France | ⭐ Référence pour la France |
| **Copernicus DEM GLO-30** | 30 m | Monde | Fallback, hors France |
| SRTM | 30–90 m | Monde | Dernier recours, bruité en montagne |

- API IGN : endpoints `elevation` (points) et `elevationLine` (profil) sur `data.geopf.fr/altimetrie` — gratuite, à confirmer pour les quotas.
- Option offline : télécharger les tuiles MNT de la zone et lire avec `rasterio` → rapide, reproductible, pas de quota.
- Chaîne de repli (`ElevationChain`) : un point sans valeur **ou une source en panne** passe à la source suivante ;
  la panne est notée dans `elevation_notes` (et `elevation_source` donne la part de chaque source). Si aucune source
  ne répond, l'outil renvoie une erreur plutôt que des altitudes partielles.
- Copernicus : seule une tuile absente (mer, 404/403 S3) donne « pas d'altitude » ; une coupure réseau est une erreur.

## Robustesse des appels (http.py)
- Miroirs Overpass : un miroir bloqué (403, 404…) ou injoignable n'empêche pas d'essayer les autres ; jamais tous
  écartés en même temps. Seul un 400 (requête invalide) arrête tout.
- Durée bornée : Overpass abandonne après 180 s (`OVERPASS_BUDGET_S`) avec un message clair, au lieu de ~10 min.

## Routage
Voir [[ADR-002 - Routage par moteur existant]].
| Moteur | + | − |
|---|---|---|
| **BRouter** | Profils rando très fins (scripts), utilise `sac_scale`, API publique, self-host léger (Java) | Doc moins moderne |
| **GraphHopper** | Profil `hike`, rapide, docker simple, API « round trip » | Profils moins fins sans config |
| OpenRouteService | Profil `foot-hiking`, API avec clé gratuite | Quotas |
| Valhalla | Très flexible | Plus lourd à opérer |

## Données complémentaires
- **refuges.info** — refuges, cabanes, points d'eau (API ouverte)
- **Waymarked Trails** — itinéraires balisés existants
- **Open-Meteo** / Météo-France — météo (plus tard)
- **Calcul du coucher du soleil** — lib `astral` (local, pas d'API)

## Licences
- OSM : **ODbL** → attribution obligatoire dans les exports (« © contributeurs OpenStreetMap »).
- IGN : Licence Ouverte Etalab 2.0 → attribution.
- Copernicus : attribution requise.
