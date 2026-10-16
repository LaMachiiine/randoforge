---
tags: [architecture]
maj: 2026-10-16
---
# Faune possible

Outil `wildlife` (`tools/nature.py`, source `engines/wildlife.py`, espèces à connaître `core/wildlife.py`).
Il liste les vertébrés **observés** autour du tracé à la même saison. Ce ne sont pas des aires de répartition :
une espèce discrète peut être présente sans être signalée.

## Source
[GBIF](https://www.gbif.org) (Global Biodiversity Information Facility), API `occurrence/search` sans clé. GBIF agrège
iNaturalist (observations validées), l'INPN et de nombreux réseaux naturalistes. Licences CC0 / CC BY selon les jeux ;
citer « GBIF.org » et ses contributeurs. iNaturalist seul a été écarté : il est déjà inclus et bien plus clairsemé.

## Méthode
- Zone : rectangle du tracé + `radius_km` (3 km par défaut).
- Période : mois de la sortie et ses deux voisins (sans changer d'année), sur les 10 dernières années.
- Par groupe (mammifères, oiseaux, reptiles, amphibiens), les espèces les plus observées (facettes `speciesKey`).
  Dans le référentiel GBIF, serpents et lézards (Squamata) sont classés à part des « Reptilia » : les deux sont
  interrogés.
- **Espèces à connaître**, cherchées à part quel que soit leur rang : genre *Vipera* (venimeuses), loup, ours brun,
  lynx. Le fait seulement, sans consigne.
- Noms français : référentiel national **TAXREF** d'abord (premier nom de la liste), puis EUNIS ; les autres listes
  contiennent des noms anciens (« Goupil », « Palombe »).

## Vérification réelle (2026-10-16)
Boucle de Lans-en-Vercors, juin–août 2016–2026 : 978 observations ; marmotte, chevreuil, renard roux, chamois ;
rougequeue noir, chocard à bec jaune ; lézard vert, couleuvre verte et jaune ; grenouille rousse, salamandre
tachetée ; à connaître : vipère aspic (1 observation, hors du haut du classement, trouvée par la recherche dédiée).
Aucun chien domestique compté comme loup dans ce secteur (les observations validées d'iNaturalist les classent à part).

## Limites
Biais d'observation (espèces visibles et zones fréquentées sur-représentées) ; peu d'observations dans les secteurs
reculés (avertissement sous 30 observations).
