# RandoForge

Serveur MCP (Python, SDK `mcp` 2.x, `MCPServer`) et plugin Claude Code pour concevoir des itinéraires de randonnée.
Conception détaillée : vault Obsidian dans `docs/` (point d'entrée `docs/00 - Accueil.md`).

## Commandes
- Tests rapides (hors ligne) : `uv run pytest`
- Tests de bout en bout (réseau, quelques minutes) : `uv run pytest -m e2e`
- Lint/format : `uv run ruff check . && uv run ruff format .`
- Serveur : `uv run randoforge` (stdio) ; démonstration : `uv run python scripts/demo_itinerance.py`
- Plugin : `claude plugin validate .`

## Structure
- `src/randoforge/core/` : calculs purs, aucune I/O — géodésie (`geo.py`), dénivelé (`elevation.py`), durée, stats, pentes et allers-retours (`terrain.py`), géométries OSM (`osmgeom.py`), points notables (`pois.py`), passages techniques (`technical.py`), zones (`areas.py`), bivouacs (`bivouac.py`), étapes (`stages.py`), qualité (`quality.py`), similarité (`similarity.py`), soleil (`sun.py`), météo (`weather.py`), boucles (`loops.py`), modèles pydantic (`models.py`). Les données externes sont passées en paramètre.
- `src/randoforge/engines/` : clients externes — BRouter, altimétrie (IGN → Copernicus, MNT local), Nominatim/Overpass, refuges.info / Open-Meteo / Wikidata (`extra.py`), itinéraires officiels Geotrek pour la calibration (`geotrek.py`).
- `src/randoforge/http.py` : client HTTP commun (cache SQLite, réessais, bascule entre serveurs, User-Agent).
- `src/randoforge/services.py` : assemblage des services (variables `RANDOFORGE_*`) ; `app.py` : contexte partagé des outils.
- `src/randoforge/tools/` : outils MCP par thème (`search`, `build`, `analyze`, `trek`, `output`) ; `schemas.py` pour les types.
- `src/randoforge/validation.py` : règles, identifiants = ceux de `docs/10 - Architecture/Validation & cohérence.md`.
- `src/randoforge/formats/` : GPX, fiche Markdown, carte HTML, roadbook ; `sections.py` = contenu commun fiche/roadbook.
- `.claude-plugin/`, `skills/planifier-rando/`, `.mcp.json` : plugin Claude Code.
- `scripts/` : démonstration de bout en bout, calibration du D+ (`calibrate_reference.py` sur les parcs nationaux, `calibrate.py` sur des traces perso).
- `tests/conftest.py` : doublures des services ; `tests/fixtures/` : vraies réponses enregistrées ; `tests/e2e/` : tests réseau.

## Conventions
- Les outils renvoient des résumés compacts, jamais la géométrie complète.
- Une erreur prévue doit lever `ToolError` : c'est le seul message que le SDK transmet au client.
- Pas de valeur silencieusement fausse : en cas de doute, `None` + un avertissement ; une règle non vérifiable le dit en `info`.
- Ne jamais écrire qu'un bivouac ou un chien est « autorisé » : signaler la zone et renvoyer au règlement.
- Les noms OSM sont modifiables par tous : toujours les échapper dans le HTML.
- Tout changement de paramètre de calcul (pas, lissage, seuil) doit être mesuré et justifié dans `docs/10 - Architecture/Calcul du dénivelé.md`.
- Documentation, messages et descriptions d'outils en français.

## Utiliser les outils pour créer un itinéraire
Voir le skill `skills/planifier-rando/SKILL.md` (démarche complète et format de réponse).
