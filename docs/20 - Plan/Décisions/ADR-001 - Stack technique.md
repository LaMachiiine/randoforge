---
tags: [adr]
statut: proposé
date: 2026-10-15
---
# ADR-001 — Stack technique

## Contexte
Il faut un serveur MCP manipulant de la géographie (projections, rasters MNT, GPX) appelé par Claude Code.

## Décision proposée
**Python 3.12+** avec :
| Besoin | Lib |
|---|---|
| Serveur MCP | `mcp` (SDK officiel, FastMCP) |
| Géodésie | `pyproj` (`Geod`) |
| Géométries | `shapely` |
| MNT local | `rasterio` + `numpy` |
| Lissage | `scipy.signal` |
| GPX | `gpxpy` |
| HTTP | `httpx` + cache SQLite |
| Modèles de données | `pydantic` |
| Tests | `pytest` |
| Gestion projet | `uv` |

## Alternatives
- **TypeScript** (SDK MCP mature, Turf.js) : écosystème raster/géodésie plus pauvre.
- **Tout via APIs, pas de code** : impossible de garantir la validation et la reproductibilité.

## Conséquences
- Écosystème géo Python très riche (GDAL sous-jacent).
- Sous Windows, `rasterio` s'installe via wheels → OK avec `uv`.
