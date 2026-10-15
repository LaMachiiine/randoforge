---
tags: [architecture, calibration]
maj: 2026-10-15
---
# Calibration du dénivelé

> Généré par `scripts/calibrate_reference.py`. Références officielles : itinéraires publiés par les parcs nationaux des Écrins et des Cévennes (plateforme Geotrek) et altitudes officielles des sommets.

## Résultats

| Mesure | Médiane des écarts absolus | Biais médian | À moins de 10 % |
|---|---|---|---|
| D+ RandoForge vs D+ publié (80 itinéraires) | 5.0 % | +0.7 % | 71 % |
| … dont ecrins | 4.2 % | +3.6 % | 75 % |
| … dont cevennes | 6.0 % | -4.4 % | 68 % |
| Même tracé, altitudes Geotrek, notre algorithme | 4.4 % | -4.4 % | 88 % |
| Distance RandoForge vs distance publiée | 0.0 % | -0.0 % | — |
| Altitude MNT au sommet vs altitude officielle — ecrins (40 sommets) | 42.8 m | -42.8 m | — |
| Altitude MNT au sommet vs altitude officielle — cevennes (23 sommets) | 1.0 m | -0.2 m | — |

## Grille lissage × seuil (médiane des écarts absolus de D+)

| Lissage \ seuil | 0 m | 2 m | 3 m | 5 m | 8 m |
|---|---|---|---|---|---|
| 0 m | 15.7 % | 8.6 % | 8.8 % | 5.8 % | 5.4 % |
| 30 m | 7.7 % | 6.1 % | 6.1 % | 5.0 % | 4.5 % |
| 60 m | 4.8 % | 4.4 % | 4.3 % | 4.4 % | 5.5 % |
| 100 m | 4.8 % | 4.9 % | 5.1 % | 5.4 % | 5.4 % |

### Par parc (le réglage global optimal peut favoriser un parc au détriment de l'autre)

| Réglage (lissage / seuil) | Écart médian par parc |
|---|---|
| 30 m / 5 m | ecrins 4.2 % (biais +3.6 %) · cevennes 6.0 % (biais -4.4 %) |
| 60 m / 3 m | ecrins 2.2 % (biais +1.7 %) · cevennes 10.1 % (biais -8.3 %) |

Meilleur réglage sur cet échantillon : lissage 60 m, seuil 3 m (4.3 %) ; réglage par défaut (30 m, 5 m) : 5.0 %.

## Itinéraires

| Parc | Itinéraire | km | D+ publié | D+ RandoForge | Écart | D+ algo seul |
|---|---|---|---|---|---|---|
| ecrins | À la découverte des hameaux de Vallouise et Pelvoux | 11.0 | 351 | 362 | +3.1 % | 320 |
| ecrins | Ancien fort de la Lausette depuis Terre Rouge | 15.3 | 935 | 1042 | +11.4 % | 913 |
| ecrins | Au-dessus des Drac | 11.8 | 701 | 802 | +14.4 % | 691 |
| ecrins | Autour des Vigneaux et de Grand Parcher | 10.7 | 253 | 276 | +9.1 % | 240 |
| ecrins | Balade autour des hameaux de Villar d'Arène | 6.6 | 180 | 227 | +26.1 % | 176 |
| ecrins | Col des Acles | 12.5 | 834 | 841 | +0.8 % | 824 |
| ecrins | Col des Marsailles | 7.6 | 568 | 593 | +4.4 % | 568 |
| ecrins | Col des Muandes | 13.8 | 841 | 847 | +0.7 % | 829 |
| ecrins | Col des Orres | 11.0 | 732 | 727 | -0.7 % | 730 |
| ecrins | Col des Ourdeis | 4.6 | 291 | 293 | +0.7 % | 291 |
| ecrins | La boucle de Roche Moutte par la bergerie | 6.6 | 542 | 551 | +1.7 % | 541 |
| ecrins | La boucle des balcons de Névache | 9.7 | 355 | 389 | +9.6 % | 327 |
| ecrins | La boucle de Tirière | 9.5 | 679 | 686 | +1.0 % | 664 |
| ecrins | La boucle du Chemin de Ronde, Lac Laramon et Cascade de Fontcouverte | 13.5 | 685 | 675 | -1.5 % | 659 |
| ecrins | La boucle du Creux des Souches | 6.4 | 504 | 483 | -4.2 % | 472 |
| ecrins | La Croix d'Aquila | 7.0 | 919 | 607 | -33.9 % | 872 |
| ecrins | La Croix de Toulouse | 6.6 | 627 | 638 | +1.8 % | 627 |
| ecrins | Lac Sainte Marguerite | 10.8 | 591 | 615 | +4.1 % | 586 |
| ecrins | L'adret de Chorges | 9.6 | 375 | 406 | +8.3 % | 375 |
| ecrins | La grande boucle Le Cuchon/Rouanne | 15.2 | 686 | 682 | -0.6 % | 664 |
| ecrins | Le Cuchon | 11.1 | 723 | 736 | +1.8 % | 716 |
| ecrins | Le fort des Salettes depuis La Vachette | 5.4 | 231 | 310 | +34.2 % | 216 |
| ecrins | Le glacier Noir | 6.4 | 513 | 536 | +4.5 % | 513 |
| ecrins | Le GR54 de La Grave à Arsine | 11.2 | 402 | 511 | +27.1 % | 391 |
| ecrins | Le Grand Glaiza - Punta Merciantaira | 15.8 | 1239 | 1233 | -0.5 % | 1231 |
| ecrins | Le plateau du Taillefer | 15.8 | 959 | 1045 | +9.0 % | 938 |
| ecrins | Le Pré de l'Aubre | 5.4 | 170 | 171 | +0.6 % | 170 |
| ecrins | Le promontoire de Prégentil | 5.2 | 296 | 317 | +7.1 % | 296 |
| ecrins | Le ravin des Merles | 7.0 | 420 | 447 | +6.4 % | 413 |
| ecrins | Le refuge Adèle Planchard | 24.8 | 1526 | 1537 | +0.7 % | 1492 |
| ecrins | Les lacs de Pétarel par les Andrieux | 10.0 | 1063 | 1054 | -0.8 % | 1055 |
| ecrins | Les lacs de Pétarel par les Portes | 12.0 | 906 | 927 | +2.3 % | 872 |
| ecrins | Les lacs d'Orcières | 7.1 | 96 | 139 | +44.8 % | 93 |
| ecrins | Les lacs du Plateau d’Emparis au départ de Besse | 18.3 | 1049 | 1082 | +3.1 % | 1035 |
| ecrins | Le sommet du Prorel | 12.0 | 1047 | 1037 | -1.0 % | 1045 |
| ecrins | Sentier d'art de Puy-Saint-André | 1.7 | 96 | 100 | +4.2 % | 94 |
| ecrins | Sentier de découverte des Gourniers | 1.2 | 39 | 52 | +33.3 % | 34 |
| ecrins | Sentier de découverte du bocage | 2.7 | 40 | 52 | +30.0 % | 39 |
| ecrins | Sentier de l'Abbaye | 2.2 | 90 | 107 | +18.9 % | 84 |
| ecrins | Sentier des Curattes | 7.6 | 258 | 276 | +7.0 % | 243 |
| cevennes | Aire-de-Côte | 7.8 | 223 | 166 | -25.6 % | 202 |
| cevennes | A la découverte de la forêt magique | 2.1 | 38 | 30 | -21.1 % | 30 |
| cevennes | Alzons | 5.1 | 282 | 277 | -1.8 % | 271 |
| cevennes | Arborétum de La Foux | 1.2 | 103 | 85 | -17.5 % | 92 |
| cevennes | Arboretum de l'Hort de Dieu | 4.7 | 346 | 325 | -6.1 % | 331 |
| cevennes | Arboretum de l'Hort de Dieu - court | 2.6 | 142 | 101 | -28.9 % | 129 |
| cevennes | Chemin des fileuses | 12.5 | 625 | 669 | +7.0 % | 599 |
| cevennes | Chemins du Lozère | 12.1 | 679 | 577 | -15.0 % | 596 |
| cevennes | Circuit de la corniche | 3.5 | 106 | 101 | -4.7 % | 97 |
| cevennes | Circuit de la Vierge | 1.9 | 15 | 51 | +240.0 % | 6 |
| cevennes | Col de Bès | 11.5 | 653 | 630 | -3.5 % | 590 |
| cevennes | Col de la Caumette | 7.3 | 223 | 162 | -27.4 % | 195 |
| cevennes | La crête du Suquet | 12.0 | 593 | 525 | -11.5 % | 544 |
| cevennes | La croix de Bassel | 4.7 | 306 | 317 | +3.6 % | 302 |
| cevennes | La Croix du Devois | 13.3 | 351 | 337 | -4.0 % | 318 |
| cevennes | La Dauphine | 12.5 | 434 | 360 | -17.1 % | 406 |
| cevennes | La Dent | 16.3 | 752 | 707 | -6.0 % | 700 |
| cevennes | La Diligence | 14.3 | 727 | 689 | -5.2 % | 656 |
| cevennes | Le Dolmen du Thort | 14.0 | 516 | 471 | -8.7 % | 493 |
| cevennes | Le Fossat | 10.8 | 583 | 528 | -9.4 % | 546 |
| cevennes | Le Gardonnet | 6.4 | 359 | 327 | -8.9 % | 313 |
| cevennes | Le Goulet | 10.1 | 298 | 288 | -3.4 % | 292 |
| cevennes | Le Grand Clapier | 24.4 | 950 | 802 | -15.6 % | 868 |
| cevennes | Le gué d'Hiverne | 12.6 | 518 | 526 | +1.5 % | 485 |
| cevennes | Les deux ponts | 7.1 | 283 | 277 | -2.1 % | 271 |
| cevennes | Les dolmens de la grande Pallières | 4.1 | 140 | 142 | +1.4 % | 133 |
| cevennes | Les dolmens de l’Ismaël | 9.2 | 299 | 315 | +5.4 % | 283 |
| cevennes | Les drailles perdues | 11.6 | 575 | 590 | +2.6 % | 543 |
| cevennes | Le sentier de la Hêtraie | 2.9 | 99 | 113 | +14.1 % | 96 |
| cevennes | Le sentier du Bout du Causse | 8.3 | 193 | 188 | -2.6 % | 175 |
| cevennes | Monoblet, le sentier botanique | 4.4 | 148 | 152 | +2.7 % | 143 |
| cevennes | Mont Brion de guets en gués | 9.8 | 479 | 490 | +2.3 % | 447 |
| cevennes | Montlouvier | 16.9 | 1013 | 981 | -3.2 % | 972 |
| cevennes | Moulin de Bougès | 9.2 | 497 | 457 | -8.0 % | 451 |
| cevennes | Moulin du Roure | 13.0 | 566 | 558 | -1.4 % | 525 |
| cevennes | Moure de la Gardille | 18.6 | 484 | 439 | -9.3 % | 457 |
| cevennes | Sentier des Morts | 9.1 | 339 | 337 | -0.6 % | 314 |
| cevennes | Sentier de Vialas | 3.4 | 154 | 96 | -37.7 % | 131 |
| cevennes | Sentier de Villefort | 1.5 | 36 | 37 | +2.8 % | 27 |
| cevennes | Sentier du Bocard | 2.5 | 98 | 82 | -16.3 % | 84 |

Données : © Parc national des Écrins, © Parc national des Cévennes (Geotrek), © contributeurs OpenStreetMap, IGN.
