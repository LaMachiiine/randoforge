---
tags: [architecture]
maj: 2026-10-16
---
# Terrain avalancheux

Outil `avalanche_terrain` (`tools/snow.py`, calcul `core/avalanche.py`, relief `CopernicusElevation.grid`).
Il dit **où** le tracé passe sur ou sous des pentes d'où une avalanche peut partir. Ce n'est **pas** un niveau de
risque : le danger dépend de la neige du jour, que seul le bulletin d'estimation du risque d'avalanche évalue.
À utiliser quand [[Neige]] signale de la neige sur le tracé.

## Méthode
Relief Copernicus GLO-30 (30 m, monde entier), lu en grille sur le tracé + 700 m ; pente de chaque maille par
différences finies (mailles converties en mètres selon la latitude). Un point tous les 50 m le long du tracé ;
l'altitude du sentier est lue sur la même grille que les pentes (Copernicus inclut la canopée : mélanger avec
l'IGN fausserait les hauteurs en forêt).

1. **Pente traversée** : pente maximale des 9 mailles autour du point ≥ 30°.
2. **Pente au-dessus** : dans un rayon de 500 m, mailles de départ possible (30° à 55°), plus hautes que le
   sentier, vues depuis le sentier sous un angle d'au moins **22°** ; au moins 4 mailles (~0,3 ha) pour écarter
   un simple talus.
3. Tronçons : points exposés consécutifs, fusionnés s'ils sont à moins de 100 m ; tronçons de moins de 100 m ignorés.
4. Avec l'état de la neige (`snow_conditions` lancé avant, ou `prepare_dossier`) : chaque tronçon est marqué « neige
   probable » s'il chevauche un tronçon enneigé (tolérance 200 m, l'échantillonnage des deux calculs diffère) ou si
   le haut de la pente de départ au-dessus de lui dépasse la limite de la neige (la neige peut partir d'au-dessus
   d'un sentier déneigé). `part_exposee_enneigee_pct` donne la part du tracé concernée. Sans ce marquage, une
   boucle enneigée sur 0,2 km annonçait « 70 % exposé » sans distinguer les tronçons secs.

## Seuils

| Paramètre | Valeur | Pourquoi |
|---|---|---|
| Pente de départ minimale | 30° | seuil usuel des plaques (formations ANENA, classification ATES de Parcs Canada) ; la plupart des avalanches déclenchées partent entre 30° et 45° |
| Pente de départ maximale | 55° | au-delà, la neige purge en continu et s'accumule peu |
| Angle de portée | 22° | méthode de l'« angle alpha » (Lied & Bakkehøi 1980, modèle alpha-bêta de l'institut norvégien NGI) : les dépôts s'arrêtent en général quand l'angle entre le haut de la zone de départ et le point dépasse ~18 à 25° ; 22° est une valeur médiane, prudente pour des avalanches moyennes, qui ne couvre pas les avalanches extrêmes |
| Rayon | 500 m | taille de versant typique en randonnée ; les très grands couloirs peuvent porter plus loin |
| Surface minimale | 4 mailles (~0,3 ha) | écarte les talus de route et les petites barres |

## Vérification réelle (2026-10-16)
- Hautes Chaumes du Forez (34,4 km) : 6,7 % exposé, km 17,5–19,8 (pente traversée jusqu'à 42°, pente de 50° jusqu'à
  ~190 m au-dessus), sur le versant raide de Pierre-sur-Haute ; le reste du plateau ne l'est pas.
- La Flégère → Lac Blanc (Chamonix, 3 km) : 93 % exposé (pentes de 35 à 54°).

## Limites
Relief à 30 m : une barre rocheuse ou un couloir étroit peut échapper au calcul ; la forêt dense (qui retient la
neige) n'est pas prise en compte ; les avalanches extrêmes portent plus loin que l'angle de 22°.
