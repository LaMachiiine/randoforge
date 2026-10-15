---
tags: [vision, idees]
---
# Idées & Fonctionnalités

Légende priorité : 🟢 MVP · 🟡 V2 · 🔵 Plus tard

## Génération d'itinéraires
- 🟢 **Point A → B** sur sentiers réels
- 🟢 **Boucle** depuis un départ avec distance/D+ cible (« 12 km ± 1, 600 m D+ »)
- 🟢 **Via des points imposés** (sommet, lac, refuge)
- 🟡 **Boucle « intelligente »** : générer plusieurs candidates, les scorer, proposer les 3 meilleures
- 🟡 **Itinérance multi-jours** : découpage en étapes avec hébergement (refuges, gîtes) en fin d'étape
- 🟡 **Variantes** : raccourci de repli, variante par mauvais temps
- 🔵 Accès en transports en commun (départ/arrivée sur arrêt de bus/gare)

## Personnalisation
- 🟢 Profil marcheur : vitesse à plat, vitesse en montée (m/h), niveau technique max (`sac_scale`)
- 🟢 Préférences : éviter routes goudronnées, privilégier sentiers balisés (GR, PR)
- 🟡 Points d'intérêt souhaités : points de vue, cascades, lacs, eau potable
- 🟢 **Points notables le long du tracé** (rivières, cascades, lacs, points de vue, patrimoine) avec position au km → [[Points notables le long du tracé]]
- 🟡 Contraintes : enfants, chien (zones interdites en parc national !), poussette
- 🔵 Mémoire des randos déjà faites → éviter les doublons, progression

## Précision & fiabilité
- 🟢 Distance calculée en géodésique (ellipsoïde WGS84)
- 🟢 D+/D- sur MNT haute résolution avec lissage (voir [[Calcul du dénivelé]])
- 🟢 Temps estimé (méthode type DIN 33466 / FFRandonnée)
- 🟢 Validation automatique (voir [[Validation & cohérence]])
- 🟡 Pente max par segment, profil altimétrique, passages > 30 %
- 🟡 Score de confiance du tracé (qualité des données OSM sur la zone)

## Contexte & sécurité
- 🟡 Points d'eau, refuges, parkings (OSM / refuges.info)
- 🟡 Zones réglementées : parcs nationaux, réserves, terrains militaires, propriétés privées
- 🟡 Heure de coucher du soleil vs heure d'arrivée estimée
- 🔵 Météo (Météo-France / Open-Meteo), risque orageux en montagne
- 🔵 Enneigement saisonnier

## Sorties
- 🟢 GPX (importable dans Komoot, IGNrando, montre GPS)
- 🟢 Fiche rando Markdown (→ directement dans ce vault Obsidian !)
- 🟡 Carte HTML interactive (Leaflet) + profil altimétrique
- 🔵 Roadbook PDF imprimable

## Idée bonus : Obsidian comme base de randos
Chaque itinéraire généré = une note Obsidian avec frontmatter (`distance_km`, `d_plus`, `duree`, `difficulte`, `massif`) → requêtable avec **Dataview** (« toutes mes boucles < 15 km dans le Vercors »).
