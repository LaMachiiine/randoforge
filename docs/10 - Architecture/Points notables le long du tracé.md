---
tags: [architecture, poi]
statut: brouillon
---
# Points notables le long du tracé

> Indiquer automatiquement ce qui rend la rando agréable — rivières, cascades, lacs, points de vue, patrimoine… — avec leur **position au km** sur le tracé. Les données viennent d'OSM (Overpass), donc **seulement quand elles existent** : on ne complète jamais avec des suppositions.

## Deux usages
1. **Annoter** un tracé existant → outil `annotate_route` : « au km 3,2 tu longes le torrent du Furon, au km 5,8 cascade à 80 m du sentier ».
2. **Planifier** autour d'envies → `find_pois` (déjà prévu) : « une boucle qui passe par une cascade ».

## Catégories et tags OSM

| Catégorie | Tags OSM | Remarque |
|---|---|---|
| 💧 Cascades | `waterway=waterfall` | souvent un point, parfois décalé du cours d'eau |
| 💧 Rivières, torrents | `waterway=river\|stream` | **franchissements** calculés par intersection géométrique |
| 💧 Lacs, étangs | `natural=water` + `water=lake\|pond\|reservoir` | « longe le lac » si le tracé reste < 50 m sur une certaine distance |
| 💧 Sources, eau potable | `natural=spring`, `amenity=drinking_water` | utile aussi pour la sécurité (eau) |
| 🏔️ Points de vue | `tourism=viewpoint`, `tower:type=observation` | |
| 🏔️ Sommets, cols | `natural=peak` (+`ele`), `natural=saddle`, `mountain_pass=yes` | contrôle de l'altitude (règle N2) |
| 🌿 Curiosités naturelles | `natural=cave_entrance\|arch\|rock\|stone`, arbre remarquable (`natural=tree` + `denotation=natural_monument`) | |
| 🏛️ Patrimoine | `historic=castle\|ruins\|wayside_cross\|wayside_shrine\|memorial\|archaeological_site`, chapelles (`amenity=place_of_worship`) | |
| 🧺 Pause | `tourism=picnic_site`, `leisure=picnic_table`, `amenity=shelter`, `tourism=alpine_hut\|wilderness_hut` | |

### Franchissements de cours d'eau
Le croisement tracé × rivière est calculé géométriquement (`shapely`) puis qualifié par le way OSM emprunté :
- `bridge=yes` → « pont sur le … » (info)
- `ford=yes` ou croisement sans pont → **gué** → warning de validation (crue, fonte des neiges)

## Corridor et détour
- **Sur le tracé** : à moins de 50 m.
- **Petit détour** : jusqu'à 300 m (paramètre `max_detour_m`), avec le détour aller-retour estimé.
- Au-delà : ignoré, sauf si l'utilisateur le demande.

## Score « vaut le coup »
Pour que Claude mette en avant l'essentiel au lieu de lister 40 croix de chemin :

| Critère | Effet |
|---|---|
| Catégorie (cascade, point de vue, lac > patrimoine mineur) | poids de base |
| A un `name` | + |
| A un tag `wikipedia` / `wikidata` | ++ (notoriété) |
| A un tag `image` | + |
| Distance au tracé | − proportionnel au détour |

Le score est **indicatif** : l'outil renvoie tout, trié ; c'est Claude qui choisit quoi raconter.

## Sortie de `annotate_route`
```json
{
  "route_id": "r_...",
  "pois": [
    {"km": 3.2, "categorie": "riviere", "type": "franchissement", "nom": "Le Furon", "via": "pont", "score": 0.6},
    {"km": 5.8, "categorie": "cascade", "nom": "Cascade de la Pissarde", "distance_m": 80, "detour_m": 160, "wikidata": "Q…", "score": 0.9},
    {"km": 7.1, "categorie": "riviere", "type": "franchissement", "nom": null, "via": "gué", "score": 0.3}
  ],
  "warnings": ["Gué au km 7,1 : vérifier le niveau d'eau"],
  "sources": {"pois": "OpenStreetMap via Overpass, 2026-10-15"}
}
```

## Intégration
- **GPX** : chaque point notable devient un `<wpt>` (nom, catégorie) → visible sur la montre.
- **Fiche** : section « Points d'intérêt » triée par km, les mieux notés en tête du résumé.
- **Validation** : gués, absence d'eau sur longue distance (règle D6).
- **Plus tard** : courte description via Wikipedia/Wikidata quand le tag existe.

## Limites
- Couverture OSM inégale : peu de POI ≠ zone sans intérêt → le dire dans la fiche.
- Les petits ruisseaux temporaires (`intermittent=yes`) sont signalés comme tels : peut-être à sec.
