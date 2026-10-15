---
tags: [vision]
statut: brouillon
---
# Vision & Objectifs

## Le problème
Les LLM sont bons pour comprendre une envie (« une boucle de 15 km avec un lac, pas trop technique, au départ d'un parking ») mais **mauvais pour la géographie précise** : ils hallucinent des sentiers, approximent les distances et sous-estiment le dénivelé.

Les outils de cartographie (Visorando, Komoot, IGNrando…) sont précis mais peu conversationnels et peu personnalisables.

## La solution
Un **serveur MCP** (Model Context Protocol) branché sur Claude Code, qui expose des outils géographiques déterministes. Claude :
1. comprend la demande et ses contraintes,
2. cherche des points d'intérêt et des chemins réels,
3. fait calculer le tracé par un moteur de routage,
4. fait calculer distance et D+/D- sur un modèle numérique de terrain,
5. fait **valider** le tracé (cohérence, accessibilité, sécurité),
6. itère si une contrainte n'est pas respectée,
7. livre un GPX + une fiche rando lisible.

## Objectifs mesurables
| Objectif | Cible |
|---|---|
| Écart de distance vs relevé GPS réel | < 2 % |
| Écart de D+ vs référence IGN | < 5 % |
| Tracé hors chemin OSM | 0 m (hors exceptions explicites) |
| Contraintes utilisateur respectées | 100 % ou écart justifié |
| Reproductibilité | Même entrée → même tracé |

## Hors périmètre (pour l'instant)
- Application mobile / navigation en temps réel
- Alpinisme, via ferrata, hors-sentier
- Météo en direct (éventuellement plus tard, voir [[02 - Idées & Fonctionnalités]])

## Liens
- [[Architecture globale]]
- [[Roadmap]]
