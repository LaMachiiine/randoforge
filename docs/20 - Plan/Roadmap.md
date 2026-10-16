---
tags: [plan]
maj: 2026-10-16
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

## Calibration & bivouac abrité ✅ (2026-10-15)
- [x] Calibration sur 80 itinéraires officiels des parcs nationaux (Geotrek) + altitudes officielles des sommets → [[Calibration du dénivelé]]
- [x] Règle N2 (sommets acérés sous-estimés par le MNT)
- [x] Bivouac abrité : grottes, abris sous roche, abris naturels refuges.info, cabanes ; option `overnight="abri"`
- [x] Tests de référence en e2e (`tests/e2e/test_reference.py`)
- ~~Variante d'itinéraire par mauvais temps~~ : écartée (choix du projet).

## Évals, vitesse, robustesse ✅ (2026-10-16)
- [x] Évals avec de vrais agents Claude Code (`evals/`) : 20 demandes types + 8 randos officielles → [[Résultats des évals]]
- [x] Réponses d'outils compactes (−34 à −75 %), `analyze_route` (analyses + validation en un appel)
- [x] Overpass : serveurs mis en concurrence, erreurs cachées détectées ; limites IGN / BRouter / Nominatim respectées
- [x] Randos officielles des parcs : `find_official_treks`, `import_official_trek`
- [x] `weather_forecast` valide l'itinéraire dans la foulée

## Reste à faire
- [ ] Optionnel : calibrer aussi sur tes traces de montre barométrique (`scripts/calibrate.py`).
- [ ] Publication du dépôt en public.

## Stratégie de test
- **Unitaires et outils (hors ligne)** : `uv run pytest` — doublures des services, vraies réponses BRouter/Overpass enregistrées.
- **Bout en bout (réseau)** : `uv run pytest -m e2e` — serveur lancé en stdio comme par Claude Code, vrais services ; un service public indisponible saute le test au lieu de l'échouer.
- **Référence** : `tests/e2e/test_reference.py` + `scripts/calibrate_reference.py --report` (itinéraires officiels des parcs).
- **Démonstration** : `uv run python scripts/demo_itinerance.py` (traversée des Hauts-Plateaux du Vercors).

## Phase 5 — Randos réelles et robustesse ✅ (2026-10-16, v0.4.0)
- [x] `find_official_treks` / `import_official_trek` sur 44 catalogues Geotrek (registre généré) ; `import_hiking_route`
  (sentiers balisés OSM) ; `route_via_places` (reconstruction d'après un descriptif)
- [x] Fourchette de D+ plausible (le topo-guide y tombe 4 fois sur 5) ; antiméridien ; calculs locaux 10× plus rapides
- [x] Relectures complètes du code : ~60 bugs corrigés, chacun couvert par un test (`tests/test_robustesse.py`)
- [x] Boucles générées sans « épingles » ; bivouacs limités aux endroits logiques pour une nuit ; règle N1 corrigée
- [x] Évals : modes reconstruction, catalogue et descriptif → [[Résultats des évals]]
