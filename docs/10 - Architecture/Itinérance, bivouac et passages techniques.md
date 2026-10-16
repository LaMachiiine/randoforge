---
tags: [architecture, itinerance]
statut: brouillon
---
# Itinérance, bivouac et passages techniques

Trois fonctions liées : pour découper une rando sur **plusieurs jours**, il faut savoir **où dormir** (refuge, bivouac) et **où ça se corse** (passages techniques, à placer en début de journée plutôt qu'en fin d'étape fatiguée).

---

## 1. Passages techniques — `technical_passages` ✅ (implémenté le 2026-10-15)

Implémentation : `src/randoforge/core/technical.py`. Testé sur Lans → Moucherotte : sentier peu visible et pentes fortes détectés, symétriques à l'aller et au retour. La requête Overpass le long du tracé (polyligne simplifiée) peut prendre 30–50 s sur les serveurs publics la première fois (cache ensuite).

> Signaler précisément les endroits délicats : km, longueur, niveau, et **pourquoi**.

### Sources
| Indice | Source | Déjà disponible ? |
|---|---|---|
| Difficulté `sac_scale` T3 et plus (`demanding_mountain_hiking`…) | tags des segments BRouter | ✅ |
| Pente forte (> 35 % sur 100 m) | MNT, règle D2 | ✅ |
| Via ferrata `highway=via_ferrata`, échelles `ladder=yes`, câbles/mains courantes `safety_rope=yes` | Overpass sur les chemins du tracé | à faire |
| Sentier peu visible `trail_visibility=bad\|horrible\|no` | Overpass | à faire |
| Pierrier `natural=scree`, névé/glacier `natural=glacier` | Overpass (polygones traversés) | à faire |
| Dangers ponctuels `hazard=*` (chutes de pierres…) | Overpass | à faire |

### Sortie
```json
{"km": 6.45, "longueur_m": 310, "niveau": "T3", "type": "pente raide + sac_scale demanding_mountain_hiking",
 "detail": "Passage de la Cheminée : pente jusqu'à 70 %, mains utiles", "sources": ["sac_scale", "MNT"]}
```
- Les indices proches (< 100 m) sont **fusionnés** en un seul passage.
- Fiche : section « Passages techniques » + rappel de l'échelle T1–T6.
- Glacier traversé → **error** (hors périmètre randonnée).

⚠️ Pente MNT le long d'une falaise : un tracé décalé de quelques mètres donne des pentes absurdes. Croiser avec `sac_scale` ; une pente extrême sur un chemin `hiking` (T1) est probablement un artefact → le signaler comme « à vérifier ».

---

## 2. Bivouac — `find_bivouac_spots` ✅ (implémenté le 2026-10-15)

Implémentation : `src/randoforge/core/bivouac.py`. Testé sur la traversée des Hauts-Plateaux du Vercors : 42 emplacements (10 refuges.info, 8 OSM, 24 calculés). La pente est mesurée sur 5 points (centre ± 15 m). Limite : la distance aux routes n'est estimée que le long du tracé.

**Bivouac abrité** : chaque emplacement porte `abrite` (refuge, cabane, abri, grotte, abri sous roche, « abri naturel » de refuges.info). `find_bivouac_spots(abrite_seulement=True)` et `plan_stages(overnight="abri")` ne retiennent que ceux-là. Grottes : avertissements crue, chutes de pierres, faune protégée.

**Réutilisation** : les emplacements sont calculés une fois par itinéraire puis réutilisés (filtres, `plan_stages`) ; `refresh=True` force un nouveau calcul. Un résultat incomplet (source en panne) n'est pas conservé : il est recalculé au prochain appel, et `plan_stages` le signale dans ses notes.

### La réglementation d'abord
Le bivouac est **réglementé différemment selon les pays et les zones** (cœurs de parcs nationaux, réserves naturelles, arrêtés municipaux, sites classés ; règles variables en Suisse, Italie, Espagne…). RandoForge **ne dira jamais « bivouac autorisé »** :
- il détecte les zones protégées traversées (`boundary=national_park|protected_area`, réserves) et l'indique ;
- il rappelle la règle générale connue quand elle est stable (ex. France : bivouac = tente montée le soir, démontée le matin, loin des routes) **avec renvoi vers le gestionnaire** du site ;
- il ne propose pas d'emplacement dans une zone où le camping est explicitement interdit dans OSM.

### Candidats
1. **Cartographiés** : `tourism=camp_site` (`backcountry=yes`, `camp_site=basic`), aires de bivouac des parcs, `tourism=wilderness_hut` ; points « emplacement de bivouac » de **refuges.info** (API ouverte).
2. **Calculés** : points du tracé qui cumulent
   - terrain **plat** : pente < 8 % sur 20 m (MNT 1–5 m indispensable → France d'abord),
   - **eau** à moins de 500 m (source, ruisseau non intermittent, lac),
   - loin des routes (> 300 m) et des habitations,
   - hors zone humide, pierrier, couloir d'avalanche, lit de torrent (risque de crue nocturne),
   - bonus : point de vue, abri du vent (à étudier).

Sortie : km, détour, source (`OSM`, `refuges.info`, `calculé`), critères satisfaits, avertissements réglementaires. Un emplacement « calculé » est présenté comme **une piste à vérifier sur place**.

Rappel « sans trace » dans la fiche (petit groupe, une nuit, pas de feu, déchets remportés).

---

## 3. Rando sur plusieurs jours — `plan_stages` ✅ (implémenté le 2026-10-15)

Implémentation : `src/randoforge/core/stages.py`. D+/D- de chaque portion par sommes cumulées recalées sur le total exact (rapide). Sans nombre de jours, prend le minimum compatible avec la durée max. Export : `route.gpx` (itinéraire complet, une trace) + `jour-N.gpx` par étape.

### Entrées
`route_id`, nombre de jours **ou** durée max par jour, type d'hébergement (`refuge`, `bivouac`, `indifférent`), profil marcheur.

### Algorithme
1. Lister les **points de coupure possibles** : refuges/gîtes (OSM `tourism=alpine_hut|hostel|guest_house`, refuges.info), emplacements de bivouac (§2), villages (ravitaillement).
2. Pour chaque portion entre deux coupures, calculer durée DIN 33466 avec la même chaîne que `compute_stats`.
3. **Programmation dynamique** : choisir les coupures qui minimisent l'écart à la durée cible, sous contrainte de durée max par jour ; pénaliser un passage technique en fin d'étape.
4. Si aucune coupure ne permet de respecter la contrainte → le dire, proposer l'option la plus proche.

### Sorties
- Par étape : km début/fin, distance, D+/D-, durée, hébergement, points d'eau, passages techniques, points notables.
- **GPX** : une trace par jour + waypoints hébergements.
- **Fiche** : une section par jour, récapitulatif en tête.
- Validation par étape : arrivée avant la nuit (D4), eau (D6), heure de départ conseillée.

### Génération directe
Pour « 3 jours autour du Vercors », Claude enchaîne `find_pois` (refuges, sommets), `route_between` en boucle avec jusqu'à 30 points, puis `plan_stages`.
