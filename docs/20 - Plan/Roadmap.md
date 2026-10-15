---
tags: [plan]
maj: 2026-10-15
---
# Roadmap

## Phase 0 — Fondations ✅
- [x] Stack → [[ADR-001 - Stack technique]] ; serveur MCP Python (SDK `mcp` 2.x)
- [x] Objet `Route`, stockage `~/.randoforge/routes/<id>/`, cache SQLite des appels externes
- [x] Cœur de calcul : distance géodésique, D+/D- (lissage + hystérésis), durée DIN 33466
- [x] Dépôt public : README, licence MIT, CLAUDE.md, ruff, tests

## Phase 1 — A → B fiable ✅
- [x] `geocode`, `find_pois`, `route_between` (BRouter), altimétrie IGN → Copernicus ([[ADR-003 - Altimétrie mondiale]])
- [x] `annotate_route` (points notables, gués), `validate_route`, `export_route`

## Phase 2 — Boucles & personnalisation ✅
- [x] `generate_loop_candidates`, `compare_routes`, profils marcheur, `technical_passages`
- [x] Règles G4, D8, D9 ; carte HTML + profil altimétrique

## Phase 3 — Itinérance & contexte ✅
- [x] `find_bivouac_spots` (OSM, refuges.info, emplacements calculés), `plan_stages`
- [x] `route_areas` (parcs, réserves, militaire), règles A2, A3, C1
- [x] `set_constraints` + règles N4, D3, D4 (soleil), D5 (saison), D6 (eau), E1, P1
- [x] `data_quality` (G1, Q3, score de confiance), `bailout_route`, `find_hiking_routes`
- [x] MNT local (`RANDOFORGE_DEM_DIR`) ; URLs BRouter / Overpass configurables

## Phase 4 — Confort ✅
- [x] `weather_forecast` (orage, pluie, vent, gel, neige) + règle W1
- [x] `mark_done`, historique, évitement des chemins déjà faits ; `compare_with_reference`
- [x] Descriptions Wikidata, arrêts de transport en commun
- [x] Exports : GPX complet + GPX par jour, roadbook imprimable, copie dans un vault Obsidian
- [x] Plugin Claude Code + skill `planifier-rando` ; serveur découpé en modules d'outils

## Reste à faire (dépend de données ou d'usage réel)
- [ ] **Calibration** : lancer `scripts/calibrate.py` sur 10–20 traces réelles (GPX barométriques + D+ topo-guides), ajuster pas / lissage / seuil (cible < 5 %).
- [ ] **Évals** : rejouer les scénarios de [[Évals]] en conversation et corriger le skill.
- [ ] Variante « mauvais temps » calculée automatiquement (itinéraire abrité, hors crêtes).
- [ ] Publication du dépôt en public.

## Stratégie de test
- **Unitaires et outils (hors ligne)** : `uv run pytest` — doublures des services, vraies réponses BRouter/Overpass enregistrées.
- **Bout en bout (réseau)** : `uv run pytest -m e2e` — serveur lancé en stdio comme par Claude Code, vrais services ; un service public indisponible saute le test au lieu de l'échouer.
- **Démonstration** : `uv run python scripts/demo_itinerance.py` (traversée des Hauts-Plateaux du Vercors).
- **Calibration** : `scripts/calibrate.py`.
