---
tags: [architecture]
maj: 2026-10-16
---
# Accès, eau et réseau

Trois outils de `tools/access.py`, vérifiés en réel le 2026-10-16.

## `public_transport` : transports en commun
- **Source** : [Transitous](https://transitous.org) (MOTIS), sans clé, Europe ; horaires théoriques officiels des
  réseaux (GTFS ; en France via transport.data.gouv.fr, ODbL). Endpoint `stoptimes` autour d'un point (800 m).
- **Conditions d'usage** : projet open source et non commercial (RandoForge : MIT), User-Agent identifiant,
  attribution visible vers transitous.org/sources. Pas de temps réel observé.
- **Ce que l'outil donne** : arrêts à moins de 800 m du départ et de l'arrivée, passages du jour par ligne et
  direction, premier passage après l'arrivée estimée (durée × (1 + 1/6) de pauses).
- **Filtres** : lignes de covoiturage (présentées comme des bus) et simples arrivées au terminus écartées ; un même
  car vu à deux arrêts voisins (à 2 min près) compté une fois.
- **Vérifié** : Lans-en-Vercors, lundi 19/10/2026 : T64 vers Grenoble 06:45, 07:10… identique au GTFS du réseau.

## `water_and_huts` : eau, cabanes et refuges
- **Source** : API [refuges.info](https://www.refuges.info/api/doc/) (CC BY-SA) : `bbox` (détail complet) pour
  l'**état** codé (« Tari définitivement », « Débit intermittent », « Fermée », « Détruite »…) et l'équipement
  (`info_comp` : poêle, couvertures, eau à moins de 100 m…), `commentaires?id_point=…` pour les **avis datés**
  (3 derniers par point, un seul appel).
- **Conséquence ailleurs** : un point tari, détruit ou inutilisable n'est jamais compté comme eau ni proposé pour
  dormir (`find_bivouac_spots`) ; une cabane signalée fermée est déclassée et signalée.
- **Limites** : pas de date de tarissement, gardiennage seulement en texte libre (souvent périmé) : les avis datés
  font foi. Attribution : « © Les contributeurs de Refuges.info » et l'auteur de chaque commentaire.

## `mobile_coverage` : couverture mobile (France)
- **Source** : tuiles vectorielles de la carte « Mon réseau mobile » de l'Arcep (`tileserv`, z12, 4 opérateurs,
  2G/3G voix et 4G données) ; mêmes données que les fichiers publiés sous Licence Ouverte, mises à jour chaque
  trimestre. Service interne non documenté : peut changer sans préavis (cache 30 jours).
- **TLS** : le serveur n'envoie pas son certificat intermédiaire ; RandoForge embarque « GlobalSign RSA OV SSL CA
  2018 » (`src/randoforge/certs/`, émis par la racine GlobalSign R3, valable jusqu'en 2028).
- **Calcul** : un point tous les 200 m ; réseau = voix 2G/3G **ou** 4G (on appelle aussi en 4G, 112 compris) ;
  tronçons sans réseau de 200 m ou plus.
- **Limites** : couverture **théorique** déclarée par les opérateurs, à l'extérieur ; 5G non publiée ; France
  métropolitaine seulement (aucune source mondiale sans compte). Les mesures participatives (Ookla) ne couvrent pas
  la montagne.
- **Vérifié** : Hautes Chaumes du Forez : réseau sur 100 % (SFR 100 %, Bouygues 99 %, Orange 77 %, Free 67 % en
  voix) ; La Bérarde → Carrelet (Écrins) : réseau sur 42 %, sans réseau km 0–0,8 et 4,2–7,8.
