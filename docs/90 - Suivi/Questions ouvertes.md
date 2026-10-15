---
tags: [suivi]
---
# Questions ouvertes

## Tranchées (2026-10-15)
- [x] Zone géographique → **monde**, avec meilleure précision en France → [[ADR-003 - Altimétrie mondiale]]
- [x] Usage → **partagé** : dépôt GitHub public, licence MIT, installation en une commande (`uv sync`)
- [x] Le vault Obsidian est la **doc du dépôt** (`docs/`) ; les fiches générées vont dans `~/.randoforge/routes/` (configurable)

## Encore ouvertes
- [ ] Interface hors Claude (carte web) ou Claude Code suffit-il ?
- [ ] Moteur pour les boucles auto : BRouter + waypoints en étoile, round-trip GraphHopper, ou graphe local `osmnx` ?
- [ ] GPX de référence pour calibrer le D+ : traces de montre barométrique + topo-guides ? Licence de ces traces si publiées dans `tests/` ?
- [ ] Usage partagé = beaucoup d'appels : faut-il imposer une instance BRouter/Overpass self-hostée, ou laisser chacun configurer ses URL ?
- [ ] Respect des conditions d'usage des API publiques (User-Agent identifiable, cache obligatoire, 1 req/s Nominatim)
