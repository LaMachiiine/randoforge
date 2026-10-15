---
tags: [adr]
statut: proposé
date: 2026-10-15
---
# ADR-003 — Altimétrie mondiale

## Contexte
Le projet n'est pas limité à la France et sera public. La meilleure source d'altitude dépend du pays, et un outil partagé ne doit pas dépendre d'une seule API à quotas.

## Décision proposée
Une interface `ElevationProvider` (`src/randoforge/engines/base.py`) et une **chaîne de fournisseurs** : on prend le premier qui `covers()` le point.

| Ordre | Fournisseur | Couverture | Résolution |
|---|---|---|---|
| 1 | IGN RGE ALTI (API Altimétrie Géoplateforme) | France métropole + DROM | 1–5 m |
| 2 | *(plus tard)* MNT nationaux : swissALTI3D, BEV Autriche, TINITALY… | pays | 0,5–10 m |
| 3 | Copernicus DEM GLO-30 (tuiles COG lues à distance, cache local) | monde | 30 m |

- Les tuiles Copernicus se lisent en COG par requêtes HTTP partielles, sans tout télécharger (`rasterio`, interpolation bilinéaire).
- La source utilisée est toujours renvoyée dans `stats.elevation_source`.
- Un tracé à cheval sur deux couvertures (frontière) est interrogé point par point : à surveiller (marche d'altitude à la frontière → règle de validation).

## Mesure (2026-10-15)
Sur 11 points du sentier Lans-en-Vercors → Moucherotte (en partie en forêt), Copernicus est **toujours au-dessus** d'IGN : +0,5 à +20,7 m. Un biais toujours positif, de l'ordre de la hauteur des arbres, est cohérent avec un modèle de surface (canopée) — à confirmer en croisant avec l'occupation du sol → IGN en priorité, avertissement automatique quand Copernicus est utilisé.

## Conséquences
- Précision variable selon la zone : le **score de confiance** du tracé doit en tenir compte.
- Les paramètres de lissage/seuil pourront dépendre de la résolution du MNT (à calibrer, voir [[Calcul du dénivelé]]).
