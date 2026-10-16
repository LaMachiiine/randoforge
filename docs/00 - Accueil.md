---
tags: [moc]
---
# 🥾 RandoForge — Accueil

> Donner à Claude / Claude Code une **boîte à outils fiable** pour concevoir des itinéraires de randonnée personnalisés : distance et dénivelé précis, tracé vérifié sur de vrais chemins, aucune incohérence.

> **État (2026-10-16, v0.4.0)** : 28 outils ; toutes les idées retenues de [[02 - Idées & Fonctionnalités]] sont réalisées ; D+ calibré sur 80 itinéraires officiels, avec fourchette plausible ([[Calibration du dénivelé]]) ; randos nommées retrouvées dans 44 catalogues officiels, en sentier balisé OSM ou d'après leur descriptif → [[Roadmap]], [[Résultats des évals]].

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
- [[Neige]]
- [[Calibration du dénivelé]]
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
- [[Évals]] · [[Résultats des évals]]
- Consignes de l'agent : skill `skills/planifier-rando/SKILL.md` du dépôt

### Suivi
- [[Questions ouvertes]]
- [[Glossaire]]
