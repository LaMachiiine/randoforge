---
tags: [plan]
---
# Roadmap

## Phase 0 — Fondations (≈ 1 semaine)
- [x] Choisir la stack → [[ADR-001 - Stack technique]]
- [x] Squelette serveur MCP Python (SDK `mcp` 2.x, `MCPServer`) + `.mcp.json` pour Claude Code
- [x] Objet `Route` + stockage fichiers (`~/.randoforge/routes/<id>/`)
- [x] Cœur de calcul testé : distance géodésique, D+/D- (lissage + hystérésis), durée DIN 33466
- [x] Outils `import_gpx`, `compute_stats`, `get_route`, `list_routes`, `export_route` (GPX + fiche)
- [x] Base du dépôt public : README, licence MIT, CLAUDE.md, ruff, 17 tests
- [ ] Cache SQLite pour les appels externes → déplacé en phase 1 (inutile sans appel externe)
- [ ] **Jeu de référence** : 10 randos réelles (GPX + D+ topo-guide) dans `tests/fixtures/`

## Phase 1 — MVP « A → B fiable » (≈ 2 semaines)
- [ ] `geocode`, `find_pois` (Nominatim + Overpass)
- [ ] `route_between` via API BRouter publique
- [ ] Altimétrie : chaîne IGN → Copernicus ([[ADR-003 - Altimétrie mondiale]]) + outil `fetch_elevation`
- [ ] `validate_route` : règles G1–G3, G6, A1, N1–N4
- [ ] `export_route` : GPX + fiche Markdown
- [ ] Calibrer le D+ sur le jeu de référence (cible < 5 %)
- [ ] [[Brouillon CLAUDE.md]] v1 + premiers tests en conversation

**Critère de sortie** : Claude produit une boucle via 3 waypoints imposés, chiffres à < 5 % de la référence, 0 error de validation.

## Phase 2 — Boucles automatiques & personnalisation
- [ ] `generate_loop_candidates` (stratégies : waypoints en étoile, round-trip GraphHopper, sentiers balisés)
- [ ] `compare_routes` + scoring
- [ ] Profils marcheur, `estimate_time`
- [ ] Règles de validation complètes (accès, difficulté, sécurité)
- [ ] Carte HTML + profil altimétrique

## Phase 3 — Itinérance & contexte
- [ ] `split_into_stages`, refuges.info
- [ ] Zones réglementées, coucher du soleil
- [ ] Self-host BRouter/GraphHopper + MNT local (fiabilité, pas de quota)

## Phase 4 — Confort
- [ ] Skill Claude Code packagé (plugin)
- [ ] Météo, enneigement
- [ ] Mémoire des randos faites, intégration Dataview

## Stratégie de test
- **Unitaires** : calculs géo (distance connue entre deux points, D+ sur profil synthétique).
- **Référence** : écart vs randos réelles, suivi dans un tableau de bord.
- **Évals Claude** : 20 demandes types (« boucle facile en famille », « 2 jours avec refuge »…) → vérifier que Claude appelle bien les outils et respecte les contraintes.
