---
tags: [architecture, mcp]
statut: brouillon
---
# Serveur MCP — Catalogue d'outils

> C'est le **cœur du projet** : la qualité des itinéraires dépend directement de la qualité de ces outils (clarté, granularité, messages d'erreur).

## Règles de design des outils
- Noms explicites en `snake_case`, descriptions rédigées **pour Claude** (quand l'utiliser, quand ne pas l'utiliser).
- Entrées typées et bornées (ex. `distance_km` entre 1 et 60).
- Sorties **compactes** : stats + `route_id` + warnings. Jamais 5 000 coordonnées dans la réponse.
- Erreurs actionnables : `"Aucun chemin trouvé entre A et B : B est à 340 m du chemin le plus proche. Essayez snap_to_trail."`
- Chaque sortie inclut `sources` (provenance des données).

## Objet central : `Route`
```json
{
  "route_id": "r_2026-10-15_a1b2",
  "waypoints": [[45.12, 5.58], [45.10, 5.61]],
  "geometry_file": "routes/r_.../route.geojson",
  "stats": {
    "distance_km": 14.82,
    "d_plus_m": 812,
    "d_minus_m": 812,
    "alt_min_m": 1012,
    "alt_max_m": 1786,
    "duree_estimee": "5h10",
    "pente_max_pct": 38,
    "sac_scale_max": "mountain_hiking",
    "part_goudron_pct": 6
  },
  "warnings": [],
  "sources": {"routing": "brouter:hiking-mountain", "dem": "IGN RGE ALTI 5m"}
}
```

## Famille 1 — Recherche & contexte
| Outil | Entrée | Sortie |
|---|---|---|
| `geocode` | texte | lieux candidats (lat/lon, type, commune) |
| `find_pois` | bbox ou centre+rayon, types | POI (sommets avec altitude, lacs, refuges, eau, parkings) |
| `find_hiking_routes` | zone | sentiers balisés existants (GR/PR) |
| `area_info` | zone | parcs/réserves, réglementations (chiens, bivouac) |
| `annotate_route` | route_id, catégories, détour max | points notables au km près (cascades, rivières, points de vue…) → [[Points notables le long du tracé]] |

## Famille 2 — Construction de tracé
| Outil | Rôle |
|---|---|
| `snap_to_trail` | Accroche un point au chemin praticable le plus proche (renvoie la distance de snap) |
| `route_between` | Tracé A → B (→ C…) via moteur de routage, profil choisi |
| `generate_loop_candidates` | N boucles candidates depuis un départ pour une distance/D+ cible |
| `modify_route` | Ajouter/supprimer/déplacer un waypoint, inverser le sens |
| `split_into_stages` | Découpe en étapes (multi-jours) selon durée max/jour et hébergements |

## Famille 3 — Mesure
| Outil | Rôle |
|---|---|
| `compute_stats` | Distance géodésique, D+/D-, altitudes, durée — voir [[Calcul du dénivelé]] |
| `elevation_profile` | Profil altimétrique échantillonné + segments raides |
| `estimate_time` | Durée selon profil marcheur (vitesses plat / montée / descente) |
| `surface_breakdown` | % sentier / piste / goudron, répartition `sac_scale` |

## Famille 4 — Validation
| Outil | Rôle |
|---|---|
| `validate_route` | Lance toutes les règles de [[Validation & cohérence]] → `ok` / warnings / erreurs |
| `compare_routes` | Tableau comparatif de candidats |
| `check_against_reference` | Compare à un GPX réel (tests de précision) |

## Famille 5 — Export
| Outil | Rôle |
|---|---|
| `export_route` | GPX, GeoJSON, fiche Markdown, carte HTML — voir [[Formats de sortie]] |
| `import_gpx` | Charger un GPX existant pour l'analyser/le modifier |

## Famille 6 — Itinérance (à venir)
| Outil | Rôle |
|---|---|
| `technical_passages` | Passages techniques au km (niveau, pente, échelles, câbles) |
| `find_bivouac_spots` | Emplacements de bivouac, avec avertissements réglementaires |
| `plan_stages` | Découpage en étapes avec hébergement |

Voir [[Itinérance, bivouac et passages techniques]].

## MVP minimal (phase 1)
`geocode`, `find_pois`, `route_between`, `compute_stats`, `validate_route`, `export_route`.
Avec ça, Claude peut déjà construire des boucles « à la main » en enchaînant des waypoints.

## Ressources MCP (lecture seule)
- `profiles://walker` — profils marcheur enregistrés
- `routes://{route_id}` — détail d'un itinéraire
- `docs://sac_scale` — explication de l'échelle de difficulté pour Claude
