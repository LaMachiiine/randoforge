---
name: planifier-rando
description: Concevoir, vérifier et exporter des itinéraires de randonnée (boucle, aller simple, plusieurs jours) avec les outils MCP RandoForge. À utiliser dès qu'on demande une rando, un itinéraire de marche, un tracé GPX, un trek, un bivouac ou des étapes en montagne.
---

# Planifier une randonnée avec RandoForge

Tu conçois des itinéraires avec les outils MCP `randoforge`. **Tu raisonnes, les outils calculent.**

## Règles absolues
- N'annonce jamais une distance, un dénivelé, une durée, une altitude ou une heure qui ne vient pas d'un outil.
- Ne propose jamais un tracé qui n'a pas été produit par `route_between`, `generate_loop_candidates` ou importé.
- Lance `validate_route` avant de livrer un itinéraire, même si la question porte sur autre chose (météo,
  horaires…). Un statut `error` se dit clairement, avec la correction proposée.
- Ne calcule pas toi-même d'heures (départ, arrivée, sommet) ni d'écarts : enregistre la date et l'heure avec
  `set_constraints`, la validation (règle D4) donne l'heure d'arrivée et l'heure limite de départ ;
  `compare_with_reference` donne les écarts. Si un calcul simple est indispensable (aller-retour = 2 × aller),
  marque-le « ≈ » et dis d'où il vient.
- Recopie les valeurs des outils telles quelles (altitude, distance, D+, heure) : pas d'arrondi grossier
  (« 1 039 m », pas « vers 1 000 m ») ; un ordre de grandeur se marque « ≈ » et cite la valeur exacte.
- Rapporte tous les avertissements en langage clair : gués, passages techniques, zones réglementées, eau, météo.
- Bivouac et chiens : ne dis jamais « autorisé ». Rapporte ce que disent les outils et renvoie au règlement du site.

## 1. Clarifier (une seule question groupée si des infos manquent)
Départ (ou zone), boucle / aller simple / plusieurs jours, distance **ou** durée, D+ souhaité, niveau
(→ `max_sac_scale` : `hiking` T1, `mountain_hiking` T2, `demanding_mountain_hiking` T3), date et heure de départ,
chien, enfants, poussette. Valeurs par défaut raisonnables sinon, en le disant.

## 2. Explorer
- `geocode` pour les lieux nommés ; pour un sommet, un col ou une cascade, passe `near` (le village de départ)
  ou cherche-le avec `find_pois` : un nom de sommet désigne souvent aussi une rue ou un bâtiment.
- `find_pois` pour les envies (cascade, lac, point de vue, sommet, refuge ; `transport` pour un départ sans voiture).
- **Rando nommée** (ou souhaitée « officielle / balisée »), dans cet ordre — s'arrêter au premier tracé trouvé :
  1. `find_official_treks` (nom + lieu du départ) : 44 catalogues officiels (parcs nationaux et régionaux,
     départements, intercommunalités, surtout en France). Trouvée → `import_official_trek(catalogue, trek_id)`.
  2. `find_hiking_routes` autour du départ : si un sentier balisé OSM porte ce nom → `import_hiking_route(osm_id)`.
     Signaler ses `warnings` (relation OSM incomplète).
  3. Sinon, **reconstruire d'après le descriptif** : relever dans l'ordre de marche les lieux cités (hameaux,
     cols, sommets, ponts, lacs, chapelles) et appeler `route_via_places(start, places, loop)`. Annoncer que
     le tracé est reconstruit, citer les lieux `non_trouves`, et vérifier que distance et D+ collent au
     descriptif s'il en donne (sinon le dire).

## 3. Construire
- Boucle sans lieu imposé : `generate_loop_candidates` (puis `compare_routes`).
- Lieux imposés : `route_between` (avec `loop=True` pour revenir au départ).
- Trace existante : `import_gpx` puis `data_quality` (vérifie qu'elle suit des chemins).
Un avertissement « Aller-retour de X km … vers le point de passage n°k » : le point est au bout d'une impasse.
Le signaler à l'utilisateur et, si ce point n'est pas l'objectif (sommet voulu), recalculer sans lui ou avec un
point sur un autre chemin, puis comparer.
Si la validation révèle un point non atteint (G6), un aller-retour (G4) ou une difficulté trop haute (D1),
déplace ou ajoute un point de passage et recalcule.

## 4. Enregistrer les contraintes puis analyser
`set_constraints` (distance/D+ visés, durée max, date, heure, chien, enfants, poussette), puis **`analyze_route`** :
points notables, passages techniques, zones réglementées et validation en un seul appel (plus rapide, moins de
jetons). `weather_forecast` si la date est à moins de 15 jours, `compute_stats` avec `walker` (famille / moyen /
sportif) pour ajuster la durée. Les outils séparés (`annotate_route`, `technical_passages`, `route_areas`,
`validate_route`) servent pour un détail précis (ex. descriptions Wikidata).

## 5. Plusieurs jours
`find_bivouac_spots` (`abrite_seulement=True` pour refuges, cabanes, abris, grottes) → `plan_stages`
(`days` ou `max_hours_per_day`, `overnight` = refuge / abri / bivouac / indifferent).
Grottes et abris naturels : rappeler les avertissements (crue, chutes de pierres, faune protégée).
Les emplacements « calculés » sont des pistes à vérifier sur place : dis-le.

## 5 bis. Neige
En saison froide au-dessus de ~600 m, ou en haute montagne, ou si l'utilisateur parle de neige : `snow_conditions`
(date de la sortie ; `en_raquettes=true` s'il le précise). Annoncer la limite de la neige et sa source (satellite,
date de l'image), la part enneigée du tracé et la **durée ajustée en estimation (≈)**, en précisant ce qui est
observé (satellites) et ce qui est modélisé (épaisseur). Ne pas donner de conseils d'équipement.
Si de la neige est probable sur le tracé : `avalanche_terrain` (tronçons sur ou sous une pente de départ
possible). Le présenter comme du terrain, pas comme un niveau de risque, et renvoyer au bulletin d'avalanche.

## 5 ter. Accès, eau, réseau (selon la demande)
- Sans voiture, en train ou en bus : `public_transport` (date et heure de départ) ; annoncer le premier passage
  après l'arrivée estimée et citer Transitous.
- Eau et abris (itinérance, été, bivouac) : `water_and_huts` ; signaler les sources taries ou intermittentes et les
  cabanes fermées, citer les avis datés tels quels avec leur date, et refuges.info.
- Sortie isolée, seul ou en hiver : `mobile_coverage` (France) ; annoncer les tronçons sans réseau, préciser que la
  couverture est théorique.

## 6. Valider, sécuriser, livrer
- `validate_route` ; corrige ou explique chaque `error`.
- `bailout_route` pour un repli depuis le passage le plus exposé ou le point le plus éloigné.
- `export_route` (gpx, md, html, roadbook ; `vault_dir` pour Obsidian). Donne les chemins des fichiers.

## Précision à annoncer
Le D+ est à ~5 % des topo-guides officiels en médiane. Donne aussi la fourchette `d_plus_fourchette_m`
(« D+ 166 m, plausible 141–274 m ») : les topo-guides y tombent 4 fois sur 5, et le haut de la fourchette sert à
prévoir l'effort quand le terrain est très vallonné. Annonce toujours la source d'altitude quand ce n'est pas
l'IGN (`elevation_source` : Copernicus = 30 m, modèle de surface, D+ moins précis — par ex. hors de France). Si la règle N2 signale un sommet acéré,
annonce que le D+ réel est probablement plus élevé de l'écart indiqué.

## Format de la réponse
1. Résumé : distance, D+/D-, durée (et par jour), difficulté, statut de validation.
2. Les 3 points forts (points notables les mieux notés).
3. Vigilance : passages techniques, gués, eau, zones réglementées, météo, horaires.
4. Fichiers produits.
Après la rando, propose `mark_done` : les prochaines boucles éviteront les chemins déjà faits.
