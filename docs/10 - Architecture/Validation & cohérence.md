---
tags: [architecture, validation]
maj: 2026-10-15
---
# Validation & cohérence

> `validate_route` exécute toutes ces règles (`src/randoforge/validation.py`). Chaque règle renvoie `ok`,
> `info`, `warning` ou `error`, avec la position (km) et souvent une suggestion. **Claude ne présente jamais
> un itinéraire avec une `error` sans le dire.** Une règle qui ne peut pas être vérifiée le dit en `info`.

## Géométrie
| ID | Règle | Niveau |
|---|---|---|
| G1 | Trace sur des chemins cartographiés (≥ 95 %), via `data_quality` | error |
| G2 | Pas de saut > 100 m sans géométrie | error |
| G3 | Boucle demandée : arrivée à < 50 m du départ | error |
| G4 | Aller-retour sur le même tronçon (> 300 m) | warning si boucle demandée, sinon info |
| G6 | Points de passage imposés atteints (< 50 m) | error |

## Accès & réglementation
| ID | Règle | Niveau |
|---|---|---|
| A1 | Pas de chemin `access=no/private` ou `foot=no` | error |
| A2 | Parc national / réserve / zone protégée traversés, avec règles probables | warning (PNR : info) |
| A3 | Zone militaire | error |
| A4 | > 100 m sur route fréquentée (simples traversées ignorées) | warning |
| A5 | Part de goudron > maximum souhaité | warning |
| C1 | Chien demandé et zone où les chiens sont interdits / en laisse | error / warning |

## Difficulté, sécurité, publics
| ID | Règle | Niveau |
|---|---|---|
| D1 | `sac_scale` au-delà du maximum demandé | error |
| D2 | Pente > 35 % sur 100 m | warning |
| D3 | Durée (ou étape la plus longue) > durée max demandée | error |
| D4 | Arrivée après le coucher du soleil / < 30 min avant / départ de nuit ; sans heure : heure limite conseillée | error / warning / info |
| D5 | Point culminant > 2 500 m de novembre à mai | warning |
| D6 | Pas de point d'eau connu sur > 3 h de marche | warning |
| D7 | Gué (cours d'eau sans pont) | warning |
| D8 | Traversée de glacier | error |
| D9 | Via ferrata | warning |
| E1 | Enfants : sentiers T2+, passages techniques, durée > 4 h | warning |
| P1 | Poussette : sentiers, marches, pistes dégradées / pentes > 15 % | error / warning |

## Cohérence des chiffres et de la demande
| ID | Règle | Niveau |
|---|---|---|
| N0 | Altitudes manquantes | error |
| N1 | Boucle : \|D+ − D-\| ≤ \|alt. arrivée − alt. départ\| + 2 × seuil d'hystérésis (un pourcentage était trop strict sur une boucle peu dénivelée : 169/172 m signalé à tort) | warning |
| N2 | Sommet atteint dont l'altitude officielle dépasse le MNT de > 15 m (D+ sous-estimé) | warning |
| N3 | D+ ≥ altitude max − altitude de départ | error |
| N4 | Distance (±10 %) et D+ (±15 %) conformes à la demande | error |
| N5 | D+ recalculé vs D+ du moteur de routage (± max(30 m, 15 %)) | warning |

## Données & météo
| ID | Règle | Niveau |
|---|---|---|
| Q1 | Sentiers sans difficulté renseignée en montagne | info |
| Q3 | Chemins peu mis à jour dans OSM (édition médiane > 6 ans) | info |
| Q4 | Score de confiance faible | warning |
| W1 | Alertes météo du jour prévu : orage, pluie, rafales, neige, gel | warning |
| X0 | Une analyse n'a pas pu être faite (service indisponible) | info |
