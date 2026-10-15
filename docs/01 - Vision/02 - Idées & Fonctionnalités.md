---
tags: [vision, idees]
maj: 2026-10-15
---
# Idées & Fonctionnalités — état d'avancement

Légende : ✅ fait · 🟨 partiel (limite précisée) · ⏳ dépend de données à fournir

## Génération d'itinéraires
| Idée | Statut | Réalisé par |
|---|---|---|
| Point A → B sur sentiers réels | ✅ | `route_between` (BRouter) |
| Boucle avec distance / D+ cible | ✅ | `generate_loop_candidates` |
| Via des points imposés (sommet, lac, refuge) | ✅ | `route_between` avec `loop=True` |
| Boucle « intelligente » : plusieurs candidates notées | ✅ | `generate_loop_candidates` + `compare_routes` |
| Itinérance multi-jours avec hébergement | ✅ | `plan_stages` → [[Itinérance, bivouac et passages techniques]] |
| Emplacements de bivouac (cartographiés + calculés) | ✅ | `find_bivouac_spots` (OSM, refuges.info, terrain plat + eau + loin des routes) |
| Passages techniques au km | ✅ | `technical_passages` |
| Variante de repli | ✅ | `bailout_route` (vers départ, arrivée ou lieu choisi) |
| Bivouac abrité (refuge, cabane, abri, grotte, abri sous roche) | ✅ | `find_bivouac_spots(abrite_seulement)`, `plan_stages(overnight="abri")` |
| ~~Variante d'itinéraire par mauvais temps~~ | — | écartée (choix du projet : météo + repli suffisent) |
| Accès en transports en commun | ✅ | `find_pois` catégorie `transport` (arrêts de bus, gares) |
| GPX de l'itinérance complète **et** un GPX par jour | ✅ | `export_route` : `route.gpx` + `jour-N.gpx` |

## Personnalisation
| Idée | Statut | Réalisé par |
|---|---|---|
| Profil marcheur (vitesses, niveau max) | ✅ | `compute_stats` (`walker` famille / moyen / sportif), `max_sac_scale` |
| Éviter le goudron, privilégier les sentiers balisés | ✅ | règle A5, bonus balisage dans le score des boucles, `find_hiking_routes` |
| Points d'intérêt souhaités | ✅ | `find_pois` |
| Points notables le long du tracé, au km | ✅ | `annotate_route` (+ descriptions Wikidata) → [[Points notables le long du tracé]] |
| Contraintes enfants / chien / poussette | ✅ | `set_constraints` + règles E1, C1, P1 |
| Mémoire des randos faites, éviter les doublons | ✅ | `mark_done`, `list_routes(done)`, pénalité `avoid_done`, colonne `deja_fait_pct` |

## Précision & fiabilité
| Idée | Statut | Réalisé par |
|---|---|---|
| Distance géodésique WGS84 | ✅ | `core/geo.py` |
| D+/D- sur MNT avec lissage | ✅ | [[Calcul du dénivelé]] ; IGN, Copernicus, ou MNT local (`RANDOFORGE_DEM_DIR`) |
| Durée (DIN 33466) | ✅ | `core/timing.py` |
| Validation automatique | ✅ | `validate_route`, ~35 règles → [[Validation & cohérence]] |
| Pentes, profil altimétrique | ✅ | règle D2, carte HTML et roadbook |
| Score de confiance des données | ✅ | `data_quality` (altimétrie, difficulté renseignée, fraîcheur OSM, présence sur chemin) |
| Calibration du D+ | ✅ | 80 itinéraires officiels des parcs (Écrins, Cévennes) : écart médian 5 % → [[Calibration du dénivelé]] ; tes traces : `scripts/calibrate.py` |
| Altitude des sommets acérés sous-estimée par le MNT | ✅ | mesurée (−43 m dans les Écrins) et signalée par la règle N2 |
| Comparaison à une trace réelle | ✅ | `compare_with_reference` |

## Contexte & sécurité
| Idée | Statut | Réalisé par |
|---|---|---|
| Points d'eau, refuges, parkings | ✅ | `annotate_route`, `find_bivouac_spots`, règle D6 |
| Zones réglementées (parcs, réserves, militaire) | ✅ | `route_areas`, règles A2, A3, C1 |
| Propriétés privées | ✅ | règle A1 (`access=private`, `foot=no` sur les chemins) |
| Coucher du soleil vs heure d'arrivée | ✅ | règle D4 (calcul hors ligne + fuseau horaire du lieu) |
| Météo, risque d'orage | ✅ | `weather_forecast` (Open-Meteo, 15 jours) + règle W1 |
| Enneigement | ✅ | hauteur de neige prévue (W1) + règle saisonnière D5 au-delà de 2 500 m |

## Sorties
| Idée | Statut | Réalisé par |
|---|---|---|
| GPX (montre, applis) | ✅ | `export_route` (points notables et nuits en waypoints) |
| Fiche Markdown Obsidian / Dataview | ✅ | `export_route` + `vault_dir` pour copier dans un vault |
| Carte HTML interactive + profil | ✅ | `export_route` format `html` |
| Roadbook imprimable (PDF) | ✅ | format `roadbook` (HTML pensé pour l'impression → « Enregistrer en PDF ») |

## Outillage
| Idée | Statut | Réalisé par |
|---|---|---|
| Skill Claude Code packagé | ✅ | plugin `.claude-plugin/` + skill `skills/planifier-rando` |
| Auto-hébergement (routage, Overpass, MNT) | ✅ | `RANDOFORGE_BROUTER_URL`, `RANDOFORGE_OVERPASS_URLS`, `RANDOFORGE_DEM_DIR` |
| Tests de bout en bout | ✅ | `uv run pytest -m e2e` : 7 tests (scénarios en stdio + précision sur références officielles) |
| ~~Évals de Claude en conversation~~ | — | écartées (choix du projet) ; remplacées par les tests de bout en bout et de référence |

## Requête Dataview d'exemple
```dataview
TABLE distance_km AS "km", d_plus AS "D+", duree, jours, niveau_technique, fait_le
FROM #rando
WHERE distance_km < 15 AND validation != "error"
SORT d_plus ASC
```
