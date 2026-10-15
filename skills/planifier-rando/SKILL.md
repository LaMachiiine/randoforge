---
name: planifier-rando
description: Concevoir, vérifier et exporter des itinéraires de randonnée (boucle, aller simple, plusieurs jours) avec les outils MCP RandoForge. À utiliser dès qu'on demande une rando, un itinéraire de marche, un tracé GPX, un trek, un bivouac ou des étapes en montagne.
---

# Planifier une randonnée avec RandoForge

Tu conçois des itinéraires avec les outils MCP `randoforge`. **Tu raisonnes, les outils calculent.**

## Règles absolues
- N'annonce jamais une distance, un dénivelé, une durée, une altitude ou une heure qui ne vient pas d'un outil.
- Ne propose jamais un tracé qui n'a pas été produit par `route_between`, `generate_loop_candidates` ou importé.
- Lance `validate_route` avant de livrer. Un statut `error` se dit clairement, avec la correction proposée.
- Rapporte tous les avertissements en langage clair : gués, passages techniques, zones réglementées, eau, météo.
- Bivouac et chiens : ne dis jamais « autorisé ». Rapporte ce que disent les outils et renvoie au règlement du site.

## 1. Clarifier (une seule question groupée si des infos manquent)
Départ (ou zone), boucle / aller simple / plusieurs jours, distance **ou** durée, D+ souhaité, niveau
(→ `max_sac_scale` : `hiking` T1, `mountain_hiking` T2, `demanding_mountain_hiking` T3), date et heure de départ,
chien, enfants, poussette. Valeurs par défaut raisonnables sinon, en le disant.

## 2. Explorer
- `geocode` pour les lieux nommés.
- `find_pois` pour les envies (cascade, lac, point de vue, sommet, refuge ; `transport` pour un départ sans voiture).
- `find_hiking_routes` pour proposer un GR/PR existant.

## 3. Construire
- Boucle sans lieu imposé : `generate_loop_candidates` (puis `compare_routes`).
- Lieux imposés : `route_between` (avec `loop=True` pour revenir au départ).
- Trace existante : `import_gpx` puis `data_quality` (vérifie qu'elle suit des chemins).
Si la validation révèle un point non atteint (G6), un aller-retour (G4) ou une difficulté trop haute (D1),
déplace ou ajoute un point de passage et recalcule.

## 4. Enregistrer les contraintes puis analyser
`set_constraints` (distance/D+ visés, durée max, date, heure, chien, enfants, poussette), puis :
`annotate_route` (points notables, gués), `technical_passages`, `route_areas`, `weather_forecast` si la date est
à moins de 15 jours, `compute_stats` avec `walker` (famille / moyen / sportif) pour ajuster la durée.

## 5. Plusieurs jours
`find_bivouac_spots` → `plan_stages` (`days` ou `max_hours_per_day`, `overnight` = refuge / bivouac / indifferent).
Les emplacements « calculés » sont des pistes à vérifier sur place : dis-le.

## 6. Valider, sécuriser, livrer
- `validate_route` ; corrige ou explique chaque `error`.
- `bailout_route` pour un repli depuis le passage le plus exposé ou le point le plus éloigné.
- `export_route` (gpx, md, html, roadbook ; `vault_dir` pour Obsidian). Donne les chemins des fichiers.

## Format de la réponse
1. Résumé : distance, D+/D-, durée (et par jour), difficulté, statut de validation.
2. Les 3 points forts (points notables les mieux notés).
3. Vigilance : passages techniques, gués, eau, zones réglementées, météo, horaires.
4. Fichiers produits.
Après la rando, propose `mark_done` : les prochaines boucles éviteront les chemins déjà faits.
