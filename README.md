# 🥾 RandoForge

Serveur [MCP](https://modelcontextprotocol.io) et plugin **Claude Code** pour concevoir des itinéraires de randonnée :
tracés sur de vrais chemins, distance et dénivelé calculés, points notables, passages techniques, bivouacs, étapes,
météo, exports GPX.

Claude ne calcule rien lui-même : il appelle les outils RandoForge et explique leurs résultats.

## Ce qu'il fait

- **Retrouver une rando** : 44 catalogues officiels (parcs nationaux et régionaux, départements…), sentiers balisés
  OpenStreetMap, ou reconstruction d'après un descriptif.
- **Créer une rando** : boucle par distance et D+, ou passage par des lieux choisis ; itinérance sur plusieurs jours.
- **Vérifier** : distance, D+ / D- (IGN en France), durée, passages techniques, zones réglementées, eau, météo,
  heure du coucher du soleil, une trentaine de règles de cohérence.
- **Neige** : enneigement observé par satellite, limite de la neige, durée ajustée et pentes avalancheuses.
- **Accès et sécurité** : bus et trains au départ et au retour, état des sources et des cabanes (avis récents),
  couverture mobile le long du tracé (France).
- **Faune** : espèces observées autour du tracé à la même saison, dont vipères et grands prédateurs.
- **Exporter** : GPX (complet et par jour), fiche Obsidian, carte HTML, roadbook imprimable.

Exemples : *« prépare-moi le Chemin des fileuses au départ de L'Estréchure »*, *« une boucle de 12 km depuis Autrans
par une cascade »*, *« 3 jours sur les Hauts-Plateaux du Vercors en dormant en cabane »*.

## Installation

Prérequis : [uv](https://docs.astral.sh/uv/) et [Claude Code](https://claude.com/claude-code).

```bash
claude plugin marketplace add LaMachiiine/randoforge
```

```bash
claude plugin install randoforge@randoforge
```

Ouvrez une nouvelle session et demandez une rando. Pour activer ou désactiver le plugin (effet dans les sessions
suivantes) :

```bash
claude plugin disable randoforge@randoforge
```

```bash
claude plugin enable randoforge@randoforge
```

## Configuration

Facultative, par variables d'environnement :

| Variable | Rôle | Défaut |
|---|---|---|
| `RANDOFORGE_HOME` | Itinéraires et cache | `~/.randoforge` |
| `RANDOFORGE_BROUTER_URL` | Moteur de routage BRouter | `https://brouter.de/brouter` |
| `RANDOFORGE_OVERPASS_URLS` | Serveurs Overpass (séparés par des virgules) | serveurs publics |
| `RANDOFORGE_DEM_DIR` | Modèles de terrain locaux (GeoTIFF) | — |

## Développement

```bash
git clone https://github.com/LaMachiiine/randoforge.git
```

```bash
cd randoforge && uv sync
```

```bash
uv run pytest
```

Tests réseau : `uv run pytest -m e2e`. Évals avec de vrais agents : [`evals/`](evals/README.md).
Documentation complète (outils, calcul du dénivelé, règles, résultats) : vault Obsidian dans
[`docs/`](docs/00%20-%20Accueil.md).

## Licences

**Le code** est sous licence [MIT](LICENSE) : libre d'utilisation, de modification et de redistribution, y compris
commerciale, à condition de conserver la mention de copyright.

**Les données** viennent de services tiers, chacun avec sa licence. Les exports portent déjà les mentions requises ;
si vous republiez un tracé, gardez-les.

| Source | Usage | Licence |
|---|---|---|
| [OpenStreetMap](https://www.openstreetmap.org) | chemins, lieux, zones | ODbL : citer « © contributeurs OpenStreetMap » ; une base de données dérivée doit rester sous ODbL |
| [refuges.info](https://www.refuges.info) | refuges, cabanes, points d'eau | CC BY-SA |
| IGN | altitudes (France) | Licence Ouverte Etalab |
| Copernicus GLO-30 | altitudes (monde) | licence Copernicus, citation de la source |
| [Open-Meteo](https://open-meteo.com) | météo, neige modélisée | CC BY 4.0 |
| [NASA GIBS](https://nasa-gibs.github.io/gibs-api-docs/) (MODIS, VIIRS) | neige observée | données ouvertes NASA, remerciement demandé |
| Sentinel-2 (Copernicus, via [Earth Search](https://earth-search.aws.element84.com/v1)) | neige observée à 20 m | données Copernicus libres, citation de la source |
| [Transitous](https://transitous.org) | horaires de transport | données des réseaux (ODbL) ; usage open source non commercial, attribution |
| Arcep « Mon réseau mobile » | couverture mobile (France) | Licence Ouverte |
| [GBIF](https://www.gbif.org) | faune observée | CC0 / CC BY selon les jeux, citer GBIF.org |
| Catalogues [Geotrek](https://geotrek.fr) | randos officielles | celle de chaque organisme éditeur |
| [BRouter](https://brouter.de) | calcul des tracés | service public, à ménager (cache intégré) |

⚠️ Un itinéraire généré aide à préparer une sortie, il ne la remplace pas : vérifiez sur place la météo, l'état des
sentiers, l'enneigement et la réglementation.
