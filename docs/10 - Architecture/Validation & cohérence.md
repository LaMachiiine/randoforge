---
tags: [architecture, validation]
---
# Validation & cohérence

> `validate_route` exécute toutes ces règles. Chaque règle renvoie `ok`, `warning` ou `error`, avec la position (km) et une suggestion de correction. **Claude ne présente jamais un itinéraire avec une `error` non résolue.**

## Règles géométriques
| ID | Règle | Niveau |
|---|---|---|
| G1 | Chaque segment est sur un way OSM praticable à pied (distance au chemin < 15 m) | error |
| G2 | Pas de saut entre deux points consécutifs (> 100 m sans géométrie) | error |
| G3 | Boucle : départ = arrivée (< 50 m) | error |
| G4 | Pas d'aller-retour involontaire (même tronçon parcouru 2× en sens inverse, sauf si demandé) | warning |
| G5 | Pas de micro-boucle / zigzag absurde (détour > 3× la distance directe sur < 500 m) | warning |
| G6 | Waypoints demandés effectivement atteints (< 50 m) | error |

## Règles d'accès & réglementation
| ID | Règle | Niveau |
|---|---|---|
| A1 | Aucun way `access=no/private` ou `foot=no` | error |
| A2 | Traversée de parc national / réserve → rappel réglementation (chiens, bivouac) | warning |
| A3 | Terrain militaire, zone interdite | error |
| A4 | Traversée de route à fort trafic (`highway=primary/trunk`) | warning |
| A5 | Portion sur route goudronnée > seuil du profil | warning |

## Règles de difficulté & sécurité
| ID | Règle | Niveau |
|---|---|---|
| D1 | `sac_scale` max ≤ niveau max du profil | error |
| D2 | Pente > 35 % sur plus de 100 m | warning |
| D3 | Durée estimée ≤ durée max demandée | error |
| D4 | Arrivée estimée avant coucher du soleil (avec départ donné) | warning |
| D5 | Altitude > 2 500 m hors saison estivale → risque neige | warning |
| D6 | Aucun point d'eau sur > X h de marche (si demandé) | warning |

## Règles de cohérence des chiffres
| ID | Règle | Niveau |
|---|---|---|
| N1 | Boucle : \|D+ − D-\| < 1 % | error |
| N2 | Alt. max ≈ `ele` des sommets OSM traversés (< 15 m) | warning |
| N3 | D+ ≥ (alt. max − alt. départ) | error |
| N4 | Distance et D+ dans la tolérance de la demande | error |
| N5 | Les stats recalculées indépendamment = celles du moteur de routage (± 3 %) | warning |

> N5 est une **double vérification** : le moteur de routage donne ses propres stats ; on les recalcule avec notre pipeline ([[Calcul du dénivelé]]). Un gros écart signale un problème de données.

## Qualité des données
| ID | Règle | Niveau |
|---|---|---|
| Q1 | Sentiers sans `sac_scale` en zone de montagne → difficulté incertaine | warning |
| Q2 | Ways `trail_visibility=bad/horrible` | warning |
| Q3 | Zone avec peu de contributions OSM récentes | info |

## Sortie type
```json
{
  "route_id": "r_...",
  "status": "warning",
  "checks": [
    {"id": "A5", "level": "warning", "km": 3.2, "message": "1,4 km sur route D106", "suggestion": "Variante par le GR91 (+0,6 km, +40 m D+)"},
    {"id": "D2", "level": "warning", "km": 8.7, "message": "Pente 41 % sur 180 m (descente)"}
  ]
}
```
