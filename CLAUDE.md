# RandoForge

Serveur MCP (Python, SDK `mcp` 2.x, `MCPServer`) exposant des outils de conception d'itinéraires de randonnée.
Conception détaillée : vault Obsidian dans `docs/` (point d'entrée `docs/00 - Accueil.md`).

## Commandes
- Tests : `uv run pytest`
- Lint/format : `uv run ruff check . && uv run ruff format .`
- Lancer le serveur : `uv run randoforge` (stdio)

## Structure
- `src/randoforge/core/` : calculs purs, aucune I/O — géodésie (`geo.py`), dénivelé (`elevation.py`), durée, stats, points notables (`pois.py`, reçoit des éléments Overpass), modèles pydantic.
- `src/randoforge/engines/` : clients externes — BRouter, altimétrie (IGN → Copernicus), Nominatim/Overpass.
- `src/randoforge/http.py` : client HTTP commun (cache SQLite, réessais, bascule entre serveurs, User-Agent).
- `src/randoforge/validation.py` : règles de validation, identifiants = ceux de `docs/10 - Architecture/Validation & cohérence.md`.
- `src/randoforge/formats/` : GPX, fiche Markdown.
- `src/randoforge/storage.py` : un dossier par itinéraire, `route.json` fait foi.
- `src/randoforge/server.py` : outils MCP ; dépendances externes injectées via `Services`.
- `tests/conftest.py` : doublures des services ; `tests/fixtures/` : vraies réponses BRouter/Overpass enregistrées. Les tests n'appellent jamais le réseau.

## Conventions
- Les outils renvoient des résumés compacts (`RouteSummary`), jamais la géométrie complète.
- Une erreur prévue doit lever `ToolError` : c'est le seul message que le SDK transmet au client.
- Pas de valeur silencieusement fausse : en cas de doute, `None` + un avertissement.
- Tout changement de paramètre de calcul (pas, lissage, seuil) doit être mesuré et justifié dans `docs/10 - Architecture/Calcul du dénivelé.md`.
- Documentation, messages et descriptions d'outils en français.

## Utiliser les outils pour créer un itinéraire
- N'annonce jamais une distance, un dénivelé, une durée ou une altitude qui ne vient pas d'un outil.
- Signale toujours les `warnings` à l'utilisateur.
- Démarche complète : `docs/30 - Claude/Workflow de Claude.md`.
