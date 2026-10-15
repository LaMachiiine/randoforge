---
tags: [suivi]
---
# Questions ouvertes

## Tranchées (2026-10-15)
- [x] Zone géographique → **monde**, avec meilleure précision en France → [[ADR-003 - Altimétrie mondiale]]
- [x] Usage → **partagé** : dépôt GitHub public, licence MIT, installation en une commande (`uv sync`)
- [x] Le vault Obsidian est la **doc du dépôt** (`docs/`) ; les fiches générées vont dans `~/.randoforge/routes/` (configurable)

## Tranchées pendant la réalisation
- [x] Interface : Claude Code + carte HTML et roadbook exportés (pas d'application web)
- [x] Boucles auto : triangles BRouter dans plusieurs directions + bonus sentiers balisés
- [x] Services publics : cache, bascule Overpass, User-Agent, URLs configurables pour l'auto-hébergement

## Encore ouvertes
- [ ] GPX de référence pour calibrer le D+ (`scripts/calibrate.py`) : traces de montre barométrique + topo-guides ? Licence de ces traces si publiées dans `tests/` ?
- [ ] Au-delà d'un usage modéré : proposer une image Docker BRouter + Overpass prête à l'emploi ?
