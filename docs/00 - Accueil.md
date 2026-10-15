---
tags: [moc]
---
# 🥾 RandoForge — Accueil

> Donner à Claude / Claude Code une **boîte à outils fiable** pour concevoir des itinéraires de randonnée personnalisés : distance et dénivelé précis, tracé vérifié sur de vrais chemins, aucune incohérence.

> **État (2026-10-15)** : toutes les idées de [[02 - Idées & Fonctionnalités]] sont réalisées ; reste la calibration sur des traces réelles et les évals en conversation → [[Roadmap]].

## Principe directeur
**Claude raisonne, les outils calculent.**
Claude ne doit *jamais* inventer une distance, un dénivelé ou un chemin. Il orchestre des outils déterministes (routage, altimétrie, validation) et explique le résultat.

## Carte du vault
### Vision
- [[01 - Vision & Objectifs]]
- [[02 - Idées & Fonctionnalités]]

### Architecture
- [[Architecture globale]]
- [[Sources de données]]
- [[Serveur MCP - Outils]]
- [[Calcul du dénivelé]]
- [[Validation & cohérence]]
- [[Points notables le long du tracé]]
- [[Itinérance, bivouac et passages techniques]]
- [[Formats de sortie]]

### Plan
- [[Roadmap]]
- [[ADR-001 - Stack technique]]
- [[ADR-002 - Routage par moteur existant]]
- [[ADR-003 - Altimétrie mondiale]]

### Claude
- [[Workflow de Claude]]
- [[Brouillon CLAUDE.md]] (remplacé par le skill `skills/planifier-rando`)
- [[Évals]]

### Suivi
- [[Questions ouvertes]]
- [[Glossaire]]
