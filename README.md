# 🥾 RandoForge

Serveur [MCP](https://modelcontextprotocol.io) qui donne à **Claude / Claude Code** des outils fiables pour concevoir des itinéraires de randonnée : distance et dénivelé précis, tracés sur de vrais chemins, validation automatique.

> **Principe : Claude raisonne, les outils calculent.** Claude n'invente jamais une distance, un dénivelé ou un chemin ; il orchestre des outils déterministes et explique le résultat.

🚧 **Statut : phase 0** — cœur de calcul et premiers outils. Le routage et l'altimétrie arrivent en phase 1 (voir la [roadmap](docs/20%20-%20Plan/Roadmap.md)).

## Outils disponibles

| Outil | Rôle |
|---|---|
| `import_gpx` | Importe une trace GPX et calcule ses statistiques |
| `compute_stats` | Recalcule distance, D+/D-, altitudes, durée avec un profil marcheur |
| `get_route` / `list_routes` | Consulte les itinéraires enregistrés |
| `export_route` | Exporte en GPX et en fiche Markdown (compatible Obsidian) |

## Installation

Prérequis : [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/<vous>/randoforge.git
cd randoforge
uv sync
```

Ouvrez Claude Code dans ce dossier : le fichier `.mcp.json` déclare le serveur automatiquement. Pour l'ajouter depuis un autre dossier :

```bash
claude mcp add randoforge -- uv run --directory /chemin/vers/randoforge randoforge
```

Les itinéraires sont stockés dans `~/.randoforge/routes/` (modifiable avec la variable `RANDOFORGE_HOME`).

## Comment le dénivelé est calculé

Le D+ brut issu d'un modèle de terrain est gonflé par le bruit (+15 à +50 % mesurés). RandoForge :
1. rééchantillonne le tracé tous les 10 m (distance géodésique WGS84) ;
2. applique un filtre médian de 30 m contre les artefacts ;
3. ne compte une montée ou une descente qu'au-delà d'un seuil de 5 m (hystérésis par extremums).

Détails et justification : [Calcul du dénivelé](docs/10%20-%20Architecture/Calcul%20du%20d%C3%A9nivel%C3%A9.md). La durée suit la méthode DIN 33466.

## Développement

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

La documentation de conception est un vault [Obsidian](https://obsidian.md) dans [`docs/`](docs/00%20-%20Accueil.md) : vision, architecture, catalogue d'outils, règles de validation, décisions (ADR).

## Données et licences

- Code : licence [MIT](LICENSE).
- Données OpenStreetMap © contributeurs OpenStreetMap, licence ODbL — attribution incluse dans les exports.
- Altimétrie (phase 1) : IGN RGE ALTI (Licence Ouverte Etalab) en France, Copernicus DEM GLO-30 ailleurs.

⚠️ Les itinéraires générés sont une aide à la préparation. Vérifiez toujours les conditions sur place (météo, état des sentiers, réglementation).
