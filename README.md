# 🥾 RandoForge

Serveur [MCP](https://modelcontextprotocol.io) et plugin **Claude Code** qui donnent à Claude des outils fiables pour concevoir des itinéraires de randonnée : tracés sur de vrais chemins, distance et dénivelé précis, points notables, passages techniques, zones réglementées, bivouacs et étapes, météo, validation automatique, exports GPX / Obsidian / carte / roadbook.

> **Principe : Claude raisonne, les outils calculent.** Claude n'invente jamais une distance, un dénivelé ou un chemin ; il orchestre des outils déterministes et explique le résultat.

Exemples de demandes : *« une boucle de 12 km depuis Autrans qui passe par une cascade, niveau T2 max »*, *« 3 jours sur les Hauts-Plateaux du Vercors en dormant en cabane »*, *« analyse ma trace montre.gpx »*.

## Outils (26)

| Thème | Outils |
|---|---|
| Recherche | `find_official_treks` (randos officielles des parcs nationaux), `geocode`, `find_pois` (cascades, points de vue, lacs, sommets, patrimoine, eau, refuges, transports), `find_hiking_routes` (GR, PR), importables tels quels avec `import_hiking_route` |
| Construction | `import_official_trek`, `route_between` (points imposés, boucle), `generate_loop_candidates` (boucles automatiques), `import_gpx`, `bailout_route` (repli) |
| Analyse | `analyze_route` (tout en un appel), `set_constraints`, `compute_stats` (profils famille/moyen/sportif), `annotate_route` (points notables au km, gués, Wikidata), `technical_passages`, `route_areas` (parcs, réserves, militaire), `data_quality` (confiance, % sur chemin), `weather_forecast`, `compare_routes`, `compare_with_reference`, `validate_route` (~35 règles) |
| Itinérance | `find_bivouac_spots` (refuges, cabanes, abris, grottes, emplacements calculés ; option « abrité seulement »), `plan_stages` (découpage en jours, nuits à l'abri possibles) |
| Sortie | `export_route` (GPX complet + un GPX par jour, fiche Obsidian, carte HTML, roadbook imprimable), `mark_done`, `get_route`, `list_routes` |

Détail : [catalogue des outils](docs/10%20-%20Architecture/Serveur%20MCP%20-%20Outils.md) · [règles de validation](docs/10%20-%20Architecture/Validation%20%26%20coh%C3%A9rence.md).

## Installation

Prérequis : [uv](https://docs.astral.sh/uv/).

**Comme plugin Claude Code** (serveur MCP + skill `planifier-rando`) :

```bash
claude plugin marketplace add LaMachiiiine/randoforge
```

```bash
claude plugin install randoforge@randoforge
```

**Depuis le dépôt** :

```bash
git clone https://github.com/LaMachiiiine/randoforge.git
```

```bash
cd randoforge && uv sync
```

Ouvrez Claude Code dans ce dossier : `.mcp.json` déclare le serveur. Pour tester le plugin localement : `claude --plugin-dir .`

## Configuration (variables d'environnement)

| Variable | Rôle | Défaut |
|---|---|---|
| `RANDOFORGE_HOME` | Itinéraires et cache | `~/.randoforge` |
| `RANDOFORGE_BROUTER_URL` | Instance BRouter (auto-hébergement) | `https://brouter.de/brouter` |
| `RANDOFORGE_OVERPASS_URLS` | Serveurs Overpass, séparés par des virgules | 3 serveurs publics en secours |
| `RANDOFORGE_DEM_DIR` | Dossier de GeoTIFF prioritaires (MNT local, toute projection) | — |

## Sources de données

| Besoin | Source |
|---|---|
| Tracé | [BRouter](https://brouter.de) (profils `hiking-mountain`, `hiking-beta`, `shortest`) |
| Altitude | IGN RGE ALTI 1–5 m en France, Copernicus GLO-30 ailleurs, ou MNT local |
| Lieux, chemins, zones | OpenStreetMap (Nominatim, Overpass) |
| Refuges, cabanes, points d'eau | [refuges.info](https://www.refuges.info) |
| Météo, neige | [Open-Meteo](https://open-meteo.com) |
| Descriptions | Wikidata |

Les réponses sont mises en cache (`cache.sqlite`) pour ménager ces services gratuits. Pour un usage intensif, hébergez BRouter et Overpass.

## Comment le dénivelé est calculé

Le D+ brut d'un modèle de terrain est gonflé par le bruit (+15 à +50 % mesurés). RandoForge densifie le tracé tous les 10 m, recalcule les altitudes sur le MNT, applique un filtre médian de 30 m, puis ne compte une montée qu'au-delà de 5 m (hystérésis par extremums). La durée suit la méthode DIN 33466. Détails : [Calcul du dénivelé](docs/10%20-%20Architecture/Calcul%20du%20d%C3%A9nivel%C3%A9.md).

**Précision mesurée** sur 80 itinéraires officiels des parcs nationaux des Écrins et des Cévennes : écart médian de **5 %** sur le D+ avec le topo-guide, distance identique ([rapport](docs/10%20-%20Architecture/Calibration%20du%20d%C3%A9nivel%C3%A9.md)). Limite connue : les modèles de terrain tronquent les pics acérés (−43 m en médiane dans les Écrins) ; la règle N2 le signale. Chaque D+ est accompagné d'une **fourchette plausible** où tombe le topo-guide 2 fois sur 3.

## Tests

```bash
uv run pytest
```

Tests unitaires et d'outils hors ligne (doublures, vraies réponses enregistrées), en quelques secondes.

```bash
uv run pytest -m e2e
```

Tests de bout en bout sur les vrais services : le serveur est lancé en stdio comme par Claude Code (boucle à la journée, itinérance de plusieurs jours, altimétrie hors de France, réimport d'un GPX), et la précision est vérifiée sur les itinéraires officiels des parcs nationaux. Environ 8 minutes ; un service public indisponible fait sauter le test au lieu de l'échouer.

```bash
uv run python scripts/demo_itinerance.py
```

Démonstration complète commentée. `scripts/calibrate_reference.py --report` refait la calibration sur les références officielles ; `scripts/calibrate.py` compare le D+ à vos propres traces. `scripts/bench_calculs.py` mesure les calculs locaux.

## Évals avec de vrais agents

`evals/` lance de vrais agents Claude Code, limités aux outils RandoForge, sur 20 demandes types et sur des randos
réelles des parcs nationaux qu'ils doivent reconstruire ; tout est noté automatiquement (chiffres traçables jusqu'aux
outils, avertissements, écart au tracé officiel). Voir [`evals/README.md`](evals/README.md).

```bash
uv run python evals/run.py --model sonnet
```

## Sobriété en jetons

Les réponses d'outils sont conçues pour coûter peu au modèle : JSON compact (sans indentation), champs vides omis,
statistiques sans paramètres de calcul, listes plafonnées (`limit`) avec le total, avertissements communs donnés une
seule fois. Mesuré sur un itinéraire réel : −34 % à −75 % selon l'outil (`find_bivouac_spots` : 10 100 → 2 500
caractères). Les listes complètes restent disponibles dans les exports.

## Documentation

Vault [Obsidian](https://obsidian.md) dans [`docs/`](docs/00%20-%20Accueil.md) : vision, architecture, outils, règles, décisions (ADR), évals.

## Licences

- Code : [MIT](LICENSE).
- Données © contributeurs OpenStreetMap (ODbL), refuges.info (CC BY-SA), IGN (Licence Ouverte), Copernicus, Open-Meteo (CC BY 4.0) — attributions incluses dans les exports.

⚠️ Les itinéraires générés sont une aide à la préparation. Vérifiez toujours les conditions sur place : météo, état des sentiers, réglementation.
