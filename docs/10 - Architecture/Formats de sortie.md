---
tags: [architecture, export]
---
# Formats de sortie

## Dossier par itinéraire
```
routes/2026-10-15_boucle-moucherotte/
├── route.gpx        # trace + waypoints, altitudes MNT
├── route.geojson    # géométrie + propriétés par segment
├── meta.json        # stats, paramètres, sources, résultat validation
├── fiche.md         # note Obsidian
└── carte.html       # Leaflet + profil altimétrique (V2)
```

## GPX
- `<trk>` avec `<ele>` issu du MNT (pas celui du moteur de routage).
- `<wpt>` pour départ, sommets, points d'eau, refuges.
- `<metadata>` avec attribution OSM / IGN.

## Fiche Markdown (Obsidian)
Modèle : voir [[Modèle - Fiche rando]].

Le frontmatter rend les randos requêtables avec **Dataview** :
```dataview
TABLE distance_km AS "km", d_plus AS "D+", duree, difficulte
FROM #rando
WHERE massif = "Vercors" AND distance_km < 15
SORT d_plus ASC
```
