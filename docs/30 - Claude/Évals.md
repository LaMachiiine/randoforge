---
tags: [claude, evals]
---
# Évals avec de vrais agents

Environnement : dossier `evals/` du dépôt (voir `evals/README.md`). De vrais agents Claude Code (`claude -p`) n'ont
accès qu'aux outils RandoForge et au skill `planifier-rando` ; leurs réponses sont notées automatiquement.

- **20 demandes types** (`evals/scenarios.json`) : outils attendus, contraintes enregistrées, mentions obligatoires,
  aucune affirmation « autorisé », validation lancée, **chaque chiffre annoncé retrouvé dans un résultat d'outil**.
- **Randos réelles officielles** (`evals/reference.json`, parcs nationaux des Écrins et des Cévennes) : l'agent reçoit
  le nom, le type, le départ et le descriptif ; son tracé est comparé au tracé officiel (recouvrement, distance, D+).

Dernier rapport : [[Résultats des évals]].

```bash
uv run python evals/run.py --model sonnet
```
