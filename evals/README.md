# Évals RandoForge

De vrais agents **Claude Code** (`claude -p`, non interactif) reçoivent une demande d'utilisateur et n'ont accès
qu'aux outils MCP RandoForge (ni web, ni shell), avec le skill `planifier-rando` comme consigne. Leurs réponses et
leurs appels d'outils sont ensuite notés automatiquement.

## Deux familles de scénarios

| Fichier | Contenu | Notation |
|---|---|---|
| `scenarios.json` | 20 demandes types (boucle, cascade, chien, 3 jours en cabane, poussette, horaires, météo, trace GPX, GR, repli, déjà fait, Zermatt, bus, vault, roadbook, passages techniques, demandes impossibles…) | outils attendus, contraintes enregistrées, mentions obligatoires, formulations interdites (« autorisé »), validation lancée, **chaque chiffre annoncé retrouvé dans un résultat d'outil** |
| `reference.json` | randos **réelles** des parcs nationaux des Écrins et des Cévennes (généré par `build_reference.py`) : l'agent reçoit le nom, le type, le départ et le descriptif, sans tracé ni chiffres | en plus : **recouvrement avec le tracé officiel** (≥ 60 % à moins de 50 m), distance (± 20 %) et D+ (± 25 %) |

## Lancer

Prérequis : Claude Code installé et connecté (`claude auth login`).

```bash
uv run python evals/run.py --model sonnet
```

Options : `--kind behaviour|reference`, `--only 03 ref-ecrins`, `--workers 6` (défaut), `--grade-only evals/runs/<dossier>` (re-noter
sans relancer les agents). Résultats dans `evals/runs/<horodatage>/` (transcription, appels, réponse, itinéraires créés) ;
rapport copié dans `docs/30 - Claude/Résultats des évals.md`, avec la **consommation** (jetons par scénario, outils dont
les réponses pèsent le plus).

## Isolation

- Chaque scénario a son propre `RANDOFORGE_HOME` (le cache HTTP est copié pour aller plus vite, les données sont les mêmes).
- `--setting-sources project` : les plugins et hooks personnels de l'utilisateur ne s'invitent pas dans l'éval.
- `--tools ""` + `--allowedTools mcp__randoforge` : l'agent ne peut rien faire d'autre qu'utiliser RandoForge.

## Coût

L'abonnement claude.ai ne facture pas à l'appel : les évals consomment le quota d'usage. Le coût affiché est l'équivalent
API estimé. Une série complète avec Sonnet : voir le dernier rapport.
