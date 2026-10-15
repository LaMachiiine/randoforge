# 🥾 RandoForge

Serveur [MCP](https://modelcontextprotocol.io) qui donne à **Claude / Claude Code** des outils fiables pour concevoir des itinéraires de randonnée : distance et dénivelé précis, tracés sur de vrais chemins, validation automatique.

> **Principe : Claude raisonne, les outils calculent.** Claude n'invente jamais une distance, un dénivelé ou un chemin ; il orchestre des outils déterministes et explique le résultat.

🚧 **Statut : phase 1** — tracés sur vrais chemins, altimétrie précise, points notables, validation. Prochaines étapes : passages techniques, boucles automatiques, itinérance et bivouac (voir la [roadmap](docs/20%20-%20Plan/Roadmap.md)).

## Outils disponibles

| Outil | Rôle |
|---|---|
| `geocode` | Coordonnées d'un lieu (village, sommet, parking…) |
| `find_pois` | Points notables autour d'un lieu pour planifier : cascades, points de vue, lacs, sommets… |
| `route_between` | Tracé sur de vrais chemins (BRouter) via des points imposés, boucle possible |
| `import_gpx` | Importe une trace GPX existante |
| `compute_stats` | Distance, D+/D-, altitudes, durée selon un profil marcheur |
| `annotate_route` | Points notables le long du tracé au km près, rivières traversées et gués |
| `validate_route` | Vérifications : points non atteints, accès interdits, difficulté, pentes, gués, cohérence des chiffres |
| `get_route` / `list_routes` | Consulte les itinéraires enregistrés |
| `export_route` | GPX (avec waypoints) et fiche Markdown (compatible Obsidian) |

Exemple de demande à Claude : *« Fais-moi une boucle de 15 km depuis Lans-en-Vercors qui passe par une cascade, niveau T2 maximum. »*

## Installation

Prérequis : [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/LaMachiiine/randoforge.git
cd randoforge
uv sync
```

Ouvrez Claude Code dans ce dossier : le fichier `.mcp.json` déclare le serveur automatiquement. Pour l'ajouter depuis un autre dossier :

```bash
claude mcp add randoforge -- uv run --directory /chemin/vers/randoforge randoforge
```

Les itinéraires sont stockés dans `~/.randoforge/routes/` (modifiable avec la variable `RANDOFORGE_HOME`).

## Sources de données

| Besoin | Source | Configurable par |
|---|---|---|
| Tracé | [BRouter](https://brouter.de) (profils `hiking-mountain`, `hiking-beta`, `shortest`) | `RANDOFORGE_BROUTER_URL` |
| Altitude | IGN RGE ALTI 1–5 m en France, sinon Copernicus GLO-30 (30 m) | — |
| Lieux, points notables | OpenStreetMap via Nominatim et Overpass (3 serveurs en secours) | `RANDOFORGE_OVERPASS_URLS` |

Les réponses sont mises en cache dans `~/.randoforge/cache.sqlite` pour respecter les services publics gratuits. Pour un usage intensif, hébergez votre propre BRouter / Overpass.

## Comment le dénivelé est calculé

Le D+ brut issu d'un modèle de terrain est gonflé par le bruit (+15 à +50 % mesurés). RandoForge :
1. rééchantillonne le tracé tous les 10 m (distance géodésique WGS84) ;
2. applique un filtre médian de 30 m contre les artefacts ;
3. ne compte une montée ou une descente qu'au-delà d'un seuil de 5 m (hystérésis par extremums).

Le tracé est d'abord densifié tous les 10 m, puis les altitudes sont recalculées sur le modèle de terrain (celles du moteur de routage sont ignorées). Détails et justification : [Calcul du dénivelé](docs/10%20-%20Architecture/Calcul%20du%20d%C3%A9nivel%C3%A9.md). La durée suit la méthode DIN 33466.

## Développement

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

La documentation de conception est un vault [Obsidian](https://obsidian.md) dans [`docs/`](docs/00%20-%20Accueil.md) : vision, architecture, catalogue d'outils, règles de validation, décisions (ADR).

## Données et licences

- Code : licence [MIT](LICENSE).
- Données OpenStreetMap © contributeurs OpenStreetMap, licence ODbL — attribution incluse dans les exports.
- Altimétrie : IGN RGE ALTI (Licence Ouverte Etalab) en France, Copernicus DEM GLO-30 ailleurs.

⚠️ Les itinéraires générés sont une aide à la préparation. Vérifiez toujours les conditions sur place (météo, état des sentiers, réglementation).
