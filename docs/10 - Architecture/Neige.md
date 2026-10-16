---
tags: [architecture]
maj: 2026-10-16
---
# Neige : enneigement le long du tracé et durée ajustée

Outil `snow_conditions` (`tools/snow.py`, calculs `core/snow.py`, sources `engines/snow.py` et `OpenMeteoSnow`).
Le but : savoir **si** le tracé est enneigé, **à partir de quelle altitude**, et **combien de temps en plus** il faut
compter. Pas de conseils d'équipement (hors du rôle du MCP).

## Quand
Saison froide (octobre → juin dans l'hémisphère nord, avril → décembre au sud) si le point culminant dépasse
**600 m** ; toute l'année au-dessus de **2 000 m** (névés, haute montagne). Sinon l'outil répond « non analysé »
(`force=True` pour analyser quand même).

## Sources (toutes vérifiées sans compte ni clé, 2026-10-16)

| Source | Ce qu'elle dit | Résolution / fréquence | Limites |
|---|---|---|---|
| **NASA GIBS**, couverture neigeuse NDSI de MODIS Terra et Aqua, VIIRS SNPP, NOAA-20 et NOAA-21 | neige **observée** ou non, par pixel | 500 m, quotidien, le jour même dès l'après-midi en Europe | rien sous les nuages ; grossier en vallée étroite |
| **Sentinel-2 L2A**, classe « neige/glace » (11) de la classification SCL, via le catalogue public Earth Search (AWS) | neige **observée** le long du tracé | 20 m, tous les 2 à 5 jours | nuages ; ombres du relief (classe 2, indéterminée) |
| **Open-Meteo**, meilleur modèle disponible (`snow_depth`, `snowfall`) | épaisseur et neige tombée sur 3 jours, **modélisées** | maille de 2 à 11 km | les modèles divergent fortement en relief (0 à 1,9 m à Chamonix le même jour) ; l'épaisseur n'est pas recalculée pour l'altitude exacte |

Écartées : stations Météo-France (rares en montagne, souvent arrêtées hors saison, valeurs aberrantes, fichier
départemental à télécharger), Camptocamp (comptes rendus sous CC BY-NC-ND : pas de reprise), Copernicus HR-S&I FSC
20 m (compte obligatoire), NOAA IMS (fichier de 600 Mo, analyse humaine à 1 km).

## Méthode
1. **Composite satellite** : pour chaque pixel du secteur (tracé + ~5 km), la vue sans nuage la plus récente parmi
   les 5 satellites, sur le jour de la sortie (ou aujourd'hui) et les 4 jours précédents. Décodage des tuiles PNG par
   la **couleur** de la palette (les index des classes diffèrent selon le satellite ; nuage = (0, 191, 255)).
   Neige si NDSI ≥ 0,10 (neige partielle comprise), sol nu si 0.
2. **Limite de la neige** : altitude de chaque pixel visible (IGN en France, Copernicus ailleurs), tranches de
   100 m (au moins 3 pixels) ; la limite est le bas de la tranche au-dessus de laquelle **toutes** les tranches sont
   enneigées à plus de 50 % (neige si NDSI ≥ 0,40, seuil MODIS classique).
3. **Sentinel-2** remplace l'état des points du tracé qu'il voit sans nuage (image des 6 derniers jours, moins de
   60 % de nuages).
4. **État par tronçon** (tous les 250 m) : vu par satellite ; sinon (nuage) neige si au-dessus de la limite ; sinon
   selon le modèle (épaisseur ≥ 2 cm). Épaisseur et neige fraîche (≥ 5 cm tombés en 3 jours) : point modèle le plus
   proche (25 points par appel).
5. **Durée** : chaque tronçon enneigé est multiplié par le facteur ci-dessous ; le rapport obtenu est appliqué à la
   durée DIN 33466 de l'itinéraire. Annoncée comme une **estimation (≈)**.

## Facteurs de durée (temps « été » × facteur)

| Neige | À pied | En raquettes |
|---|---|---|
| peu épaisse (≤ 10 cm) ou tassée | 1,25 | 1,25 |
| fraîche 10 à 20 cm | 1,5 | 1,4 |
| fraîche 20 à 40 cm | 2,0 | 1,7 |
| fraîche > 40 cm | 3,0 | 2,2 |
| ancienne, épaisse (> 10 cm, non damée) | 1,5 | 1,4 |

D'où viennent ces chiffres (valeurs prudentes, haut des fourchettes) :
- **Suisse Rando / OFROU** (guide « Winterwanderwege und Schneeschuhrouten », confirmé par Plattform J,
  17.01.2024) : temps d'été × 1,25 sur chemin hivernal damé, × 1,5 sur itinéraire raquettes non damé.
- **Coefficients de terrain de Pandolf** (Soule & Goldman 1972 ; Pandolf et al. 1976, *Ergonomics* 19(6)) : neige
  dure 1,6 ; neige molle 15 / 25 / 35 cm : 2,5 / 3,3 / 4,1. À puissance égale, cela donne sur le plat ×1,26, ×1,58,
  ×1,82, ×2,02 (conversion RandoForge, non publiée).
- **Connolly 2002** (*J Strength Cond Res* 16(4)) : en raquettes, à dépense égale, vitesse × 0,74 en neige tassée,
  × 0,51 en neige non tassée.
- **US Army ATP 3-90.97** (2016, tableau 4-1) : à pied dans plus de 30 cm de neige non tracée, 0,5 à 1 km/h ;
  en raquettes 1,5 à 3 km/h (« rough guide »).

Seuls Connolly, Smolander (1989) et les coefficients de Pandolf sont **mesurés** ; le reste est empirique. Pente,
croûte, neige transformée et trace à faire ne sont pas modélisés.

## Vérification réelle (2026-10-16)
- Hautes Chaumes du Forez (34,4 km, 1 036 → 1 624 m), le 15/02/2026 : limite de la neige ~1 300 m (satellites,
  79 % du secteur visible), neige probable sur 86 % du tracé, durée 12h09 → ≈ 15h37 à pied, ≈ 15h19 en raquettes.
- Même tracé le 16/10/2026 : aucune neige vue jusqu'à 1 624 m (satellites), confirmé par Sentinel-2 du 15/10 sur
  100 % du tracé.
- Chamonix, 15/02/2025 : MODIS et VIIRS placent tous deux la limite vers 1 000–1 200 m.

## Attributions
« Imagery provided by services from NASA's Global Imagery Browse Services (GIBS), part of NASA's ESDIS » ;
« Contains modified Copernicus Sentinel data » ; Open-Meteo (CC BY 4.0).
