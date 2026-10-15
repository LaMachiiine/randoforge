---
tags: [adr]
statut: proposé
date: 2026-10-15
---
# ADR-002 — Routage par moteur existant

## Contexte
Calculer un chemin réaliste sur le réseau OSM demande un graphe, des profils de coût (pente, `sac_scale`, surface) et des perfs. Le réécrire serait long et moins fiable.

## Décision proposée
1. **Phase 1** : API publique **BRouter** (profils rando, prise en compte de `sac_scale` et du dénivelé).
2. **Phase 3** : self-host BRouter (ou GraphHopper en Docker) pour la fiabilité et des profils sur mesure.
3. Le serveur MCP expose une **interface `RoutingEngine`** abstraite → moteur interchangeable.

## Ce que l'on garde chez nous
Le moteur ne fait **que** le tracé. Les stats (distance, D+) et la validation sont **recalculées par notre pipeline**, pour être homogènes quelle que soit la source → règle N5 de [[Validation & cohérence]].

## Alternatives
- `osmnx` + `networkx` en local : parfait pour expérimenter / générer des boucles sur petite zone, lent sur grande zone. → Piste pour `generate_loop_candidates`.
