---
tags: [architecture, algo]
---
# Calcul de la distance et du dénivelé

> Le D+ est **le chiffre le plus souvent faux** dans les outils de rando. Cause principale : le bruit du MNT et de l'échantillonnage, qui s'accumule à chaque petite oscillation.

## Distance
- Calcul **géodésique** sur l'ellipsoïde WGS84 (`pyproj.Geod.inv` ou `geographiclib`), pas Haversine sphérique ni distance plane.
- Distance **2D** (convention de toutes les applis de rando). La distance 3D peut être donnée à titre informatif (+1 à 3 % en montagne).
- Densifier le tracé si des segments sont longs (> 50 m) avant l'échantillonnage altimétrique.

## Pipeline D+ / D-
```mermaid
flowchart LR
    A[Géométrie du tracé] --> B[Rééchantillonnage<br/>pas fixe 10–20 m]
    B --> C[Altitude MNT<br/>interpolation bilinéaire]
    C --> D[Lissage<br/>médiane / Savitzky-Golay]
    D --> E[Seuil d'hystérésis<br/>~5 m]
    E --> F[D+ / D-]
```

1. **Rééchantillonnage à pas fixe** (ex. 10 m) : rend le résultat indépendant de la densité de points du moteur de routage.
2. **Altitude MNT** avec interpolation bilinéaire (pas plus-proche-voisin).
3. **Lissage** : filtre médian de **30 m** (3 points) pour retirer pics et artefacts.
4. **Hystérésis par extremums** : une montée n'est validée qu'au moment où l'on redescend d'au moins le seuil (**5 m** par défaut) depuis le point le plus haut atteint, et inversement.
5. Les paramètres (pas, fenêtre, seuil) sont **renvoyés dans les métadonnées** pour la traçabilité.

### Hystérésis : pourquoi suivre les extremums
Une version naïve (« compter dès qu'on s'écarte du seuil depuis le dernier point validé ») perd jusqu'au seuil à chaque sommet et chaque col : sur une montée à 102 m elle donne 100 m. La version implémentée (`core/elevation.py`) garde l'extremum candidat et le valide au demi-tour → 102 m. Couvert par un test.

### Mesures ayant fixé les valeurs par défaut (2026-10-15)
Profils synthétiques, pas de 10 m, seuil 5 m — D+ calculé :

| Fenêtre médiane | Sommet en V, 300 m, pente 30 % | 500 m + bruit MNT σ = 2 m | 500 m + pics isolés de 25 m |
|---|---|---|---|
| 0 (aucune) | 300 | 580 (+16 %) | 740 (+48 %) |
| **30 m** | **297** | **502** | **523** |
| 60 m | 294 | 502 | 521 |
| 100 m | 291 | 502 | 519 |

→ 30 m élimine le bruit et ne coûte que ~3 m sur un sommet très pointu. Au-delà, on écrête les sommets sans gain. (Les ~20 m restants dans la colonne « pics » viennent des pics placés au tout premier et au tout dernier point, que le médian ne peut pas corriger aux bords.)

## Pièges connus
- **Ponts et tunnels** : le MNT donne l'altitude du terrain (fond de vallée / sommet de montagne). → Interpoler linéairement l'altitude entre les extrémités pour les ways OSM `bridge=yes` / `tunnel=yes`.
- **Falaises / sentiers en corniche** : un MNT 30 m peut « tomber » de la falaise. → Préférer RGE ALTI 1–5 m en France.
- **Boucle** : D+ doit ≈ D- (écart < 1 %). Sinon, bug → vérifié par [[Validation & cohérence]].
- **Altitudes des sommets** : comparer l'altitude max calculée au tag `ele` OSM du sommet traversé (écart attendu < 10–15 m).

## Calibration
Constituer un **jeu de référence** de 10–20 randos connues (GPX barométriques + topo-guides) et ajuster `pas`, `fenêtre`, `seuil` pour minimiser l'erreur. → tâche dans [[Roadmap]].

## Estimation de durée
Méthode type **DIN 33466** (utilisée par les clubs alpins) :
- temps horizontal = distance / 4 km/h
- temps vertical = D+ / 300 m/h + D- / 500 m/h
- durée = max(h, v) + min(h, v) / 2

Paramètres ajustables par le profil marcheur. Pauses non incluses (le préciser dans la fiche).
