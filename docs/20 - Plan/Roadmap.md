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

## Phase 1 — MVP « A → B fiable » ✅ (2026-10-15)
- [x] `geocode`, `find_pois` (Nominatim + Overpass, bascule entre 3 serveurs, cache SQLite)
- [x] `route_between` via API BRouter publique (tags OSM par segment conservés)
- [x] Altimétrie : chaîne IGN → Copernicus ([[ADR-003 - Altimétrie mondiale]]), tracé densifié à 10 m
- [x] `validate_route` : G2, G3, G6, A1, A4, A5, D1, D2, D7, N0, N1, N3, N5, Q1
- [x] `export_route` : GPX (+ waypoints des points notables) + fiche Markdown
- [x] `annotate_route` : points notables le long du tracé (cascades, rivières, points de vue…), en waypoints GPX et dans la fiche
- [ ] Calibrer le D+ sur le jeu de référence (cible < 5 %)
- [ ] [[Brouillon CLAUDE.md]] v1 + premiers tests en conversation

**Critère de sortie** : Claude produit une boucle via 3 waypoints imposés, chiffres à < 5 % de la référence, 0 error de validation.

## Phase 2 — Boucles automatiques & personnalisation
- [ ] `technical_passages` : passages techniques au km → [[Itinérance, bivouac et passages techniques]]
- [ ] Règle G4 : aller-retour involontaire sur le même tronçon
- [ ] `generate_loop_candidates` (stratégies : waypoints en étoile, round-trip GraphHopper, sentiers balisés)
- [ ] `compare_routes` + scoring
- [ ] Profils marcheur, `estimate_time`
- [ ] Règles de validation complètes (accès, difficulté, sécurité)
- [ ] Carte HTML + profil altimétrique

## Phase 3 — Itinérance & contexte
- [ ] `plan_stages` (itinérance multi-jours), refuges.info
- [ ] `find_bivouac_spots` (cartographiés + calculés), zones réglementées
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
