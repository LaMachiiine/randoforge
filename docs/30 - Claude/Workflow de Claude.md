---
tags: [claude]
---
# Workflow de Claude

> Comment Claude doit raisonner pour produire un itinéraire propre. Ce workflow deviendra un **skill Claude Code** (voir [[Brouillon CLAUDE.md]]).

## 1. Clarifier la demande
Infos indispensables (demander si absentes, proposer des valeurs par défaut sinon) :
- Lieu de départ (ou zone)
- Type : boucle / A→B / multi-jours
- Distance **ou** durée cible, D+ souhaité
- Niveau (→ `sac_scale` max), contraintes (enfants, chien)
- Date (saison, durée du jour)

## 2. Explorer la zone
`geocode` → `find_pois` → `find_hiking_routes` → `area_info`
Objectif : connaître les « ingrédients » (sommets, lacs, sentiers balisés, parkings).

## 3. Construire des candidats
- Soit `generate_loop_candidates`, soit placement manuel de waypoints + `route_between`.
- Toujours **2 à 5 candidats** pour pouvoir comparer.

## 4. Mesurer et valider
`compute_stats` + `validate_route` pour chaque candidat.
- `error` → corriger (déplacer un waypoint, changer de profil) et recommencer.
- `warning` → garder mais le mentionner.

## 5. Choisir et justifier
`compare_routes` → choisir, expliquer pourquoi (écart à la cible, intérêt, sécurité).

## 6. Livrer
`export_route` → fiche Markdown + GPX. Résumé court dans la conversation.

## Règles d'or
1. **Aucun chiffre sans outil.** Pas de « environ 12 km » sorti de nulle part.
2. **Aucun chemin sans moteur de routage.**
3. **Toujours valider avant de livrer.**
4. **Transparence** : signaler les warnings et les incertitudes de données.
5. Rester dans la tolérance demandée, ou expliquer pourquoi c'est impossible et proposer l'alternative la plus proche.
