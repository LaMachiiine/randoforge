---
tags: [architecture, mcp]
maj: 2026-10-15
---
# Serveur MCP — Catalogue d'outils

> 34 outils, regroupés par module dans `src/randoforge/tools/`. Chaque outil renvoie un résumé compact
> (jamais la géométrie complète) ; un `route_id` désigne l'itinéraire stocké côté serveur.

## Règles de design
- Descriptions rédigées **pour Claude** : quand l'utiliser, ce qu'il faut en dire à l'utilisateur.
- Entrées typées et bornées ; erreurs prévues levées en `ToolError` (seul message transmis au client).
- Analyses coûteuses (Overpass) mises en cache ; `validate_route` lance celles qui manquent.
- Les sources de données sont indiquées dans les sorties (provenance, licences).

## Recherche — `tools/search.py`
| Outil | Rôle |
|---|---|
| `geocode` | Coordonnées d'un lieu par son nom (Nominatim) |
| `find_pois` | Points notables autour d'un lieu, triés par intérêt ; catégorie `transport` pour bus/gares |
| `find_official_treks` | Randos officielles de 44 catalogues Geotrek (parcs nationaux et régionaux, départements, intercommunalités ; registre `engines/geotrek_catalogs.json`, régénéré par `scripts/build_geotrek_catalogs.py`) par nom ou lieu ; seuls les catalogues couvrant le lieu sont interrogés |
| `find_hiking_routes` | Sentiers balisés (GR, PR…) proches, réseau national d'abord ; à importer avec `import_hiking_route` |

## Construction — `tools/build.py`
| Outil | Rôle |
|---|---|
| `route_between` | Tracé BRouter par des points imposés (≤ 30), boucle possible ; altitudes recalculées sur MNT |
| `generate_loop_candidates` | Boucles automatiques (triangles dans 3–12 directions), notées et mesurées |
| `import_official_trek` | Import du tracé officiel d'un catalogue, recalculé (D+ comparé au topo-guide) |
| `route_via_places` | Rando reconstruite d'après les lieux de passage de son descriptif : lieux cherchés près du départ, introuvables listés, jamais devinés |
| `import_hiking_route` | Import d'un sentier balisé OSM (relation trouvée par `find_hiking_routes`) : chemins mis bout à bout, variantes ignorées, trous signalés |
| `import_gpx` | Import d'une trace (altitudes du fichier ou du MNT) |
| `bailout_route` | Itinéraire de repli depuis un km vers le départ, l'arrivée ou un lieu |

## Analyse — `tools/analyze.py`
| Outil | Rôle |
|---|---|
| `analyze_route` | Points notables + passages techniques + zones (en parallèle) + validation, en un appel |
| `set_constraints` | Distance/D+ visés, durée max, date et heure, chien, enfants, poussette… |
| `compute_stats` | Distance, D+/D-, altitudes, durée (profils famille / moyen / sportif) |
| `annotate_route` | Points notables au km, gués, descriptions Wikidata |
| `technical_passages` | Passages techniques (T3+, pente, via ferrata, échelles, câbles, pierriers, glaciers, refuges.info) |
| `route_areas` | Zones réglementées traversées (parcs, réserves, militaire) |
| `data_quality` | Score de confiance, % sur chemin cartographié, fraîcheur OSM, part balisée |
| `snow_conditions` | Enneigement : neige observée par satellite (MODIS/VIIRS 500 m, Sentinel-2 20 m), limite de la neige, épaisseur modélisée, durée ajustée → [[Neige]] |
| `avalanche_terrain` | Tronçons sur ou sous une pente de départ d'avalanche possible (relief 30 m, angle de portée) → [[Terrain avalancheux]] |
| `public_transport` | Arrêts et horaires du jour au départ et à l'arrivée, premier passage après l'arrivée estimée (Transitous) → [[Accès, eau et réseau]] |
| `water_and_huts` | Points d'eau, cabanes, refuges : état (tari, fermée…), équipement, derniers avis datés (refuges.info) |
| `mobile_coverage` | Couverture mobile théorique le long du tracé, tronçons sans réseau, par opérateur (Arcep, France) |
| `wildlife` | Faune observée autour du tracé à la saison (GBIF) et espèces à connaître (vipères, grands prédateurs) → [[Faune]] |
| `weather_forecast` | Prévisions Open-Meteo au départ / point culminant / arrivée sur la plage de marche |
| `compare_routes` | Tableau comparatif (dont goudron, balisage, déjà fait) |
| `compare_with_reference` | Écart à une trace de référence |
| `validate_route` | Toutes les règles de [[Validation & cohérence]] |

## Itinérance — `tools/trek.py`
| Outil | Rôle |
|---|---|
| `find_bivouac_spots` | Refuges, cabanes, aires de bivouac et emplacements calculés, avec avertissements réglementaires |
| `plan_stages` | Découpage en jours (programmation dynamique sur les hébergements) |

## Sortie & historique — `tools/output.py`
| Outil | Rôle |
|---|---|
| `get_route`, `list_routes` | Consultation (filtre randos faites / projets) |
| `mark_done` | Historique ; évité ensuite par les boucles générées |
| `export_route` | `gpx` (complet + un fichier par jour), `md`, `html`, `roadbook` ; copie dans un vault |

## Objet central : `Route` (`core/models.py`)
Points densifiés à 10 m avec altitudes MNT, segments et tags OSM du moteur, contraintes (`RouteRequest`),
statistiques, puis résultats d'analyse optionnels : `pois`, `technical`, `areas`, `bivouacs`, `stages`,
`weather`, `quality`, `validation`, historique (`done_on`).
