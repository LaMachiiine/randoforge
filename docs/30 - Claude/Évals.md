---
tags: [claude, evals]
---
# Évals — demandes types

Scénarios à rejouer en conversation avec le plugin installé. Pour chacun : les outils attendus et ce qui
doit apparaître dans la réponse. Un scénario échoue si Claude annonce un chiffre sans outil, livre un
`error` sans le dire, ou affirme qu'un bivouac / un chien est « autorisé ».

| # | Demande | Outils attendus | La réponse doit… |
|---|---|---|---|
| 1 | « Boucle de 12 km depuis Autrans, pas trop dure » | geocode, generate_loop_candidates, set_constraints, validate_route | proposer 2–3 boucles comparées, distance ±10 % |
| 2 | « Une rando qui passe par une cascade près de Villard-de-Lans » | find_pois (cascade), route_between loop | citer la cascade et sa position au km |
| 3 | « Le Moucherotte depuis Lans, avec mon chien » | route_between, set_constraints with_dog, route_areas, validate_route | signaler les zones et règles chiens, sans dire « autorisé » |
| 4 | « 3 jours sur les Hauts-Plateaux en dormant en cabane » | route_between, find_bivouac_spots, plan_stages overnight=refuge | donner les 3 étapes, l'eau (rare !), la réserve naturelle |
| 5 | « Boucle facile avec une poussette » | generate_loop_candidates, set_constraints stroller | refuser/corriger les sentiers (P1) |
| 6 | « Sortie en famille avec enfants de 6 ans, 2 h max » | compute_stats walker=famille, set_constraints | durée famille, règle E1 |
| 7 | « Je pars samedi à 15 h, j'ai le temps ? » | set_constraints date+start_time, validate_route (D4) | heure d'arrivée vs coucher du soleil |
| 8 | « Météo pour ma rando de demain ? » | weather_forecast | orage / gel / vent au point culminant |
| 9 | « Analyse ma trace montre.gpx » | import_gpx, data_quality, technical_passages | % sur chemin, passages, D+ fichier vs MNT |
| 10 | « Compare ma trace à l'itinéraire prévu » | compare_with_reference | écart moyen / max, écart D+ |
| 11 | « Un GR près de Corrençon ? » | find_hiking_routes | GR 91 en tête |
| 12 | « Et si je dois redescendre au km 8 ? » | bailout_route | distance et D+ du repli |
| 13 | « J'ai fait la boucle de dimanche » puis « une autre boucle depuis le même parking » | mark_done, generate_loop_candidates avoid_done | boucle différente (deja_fait_pct bas) |
| 14 | « Une rando au départ de Zermatt » | route_between | prévenir que l'altimétrie Copernicus est moins précise |
| 15 | « Itinéraire sans voiture, départ d'une gare » | find_pois transport, route_between | départ sur arrêt/gare réel |
| 16 | « Exporte tout dans mon vault Obsidian » | export_route vault_dir | chemins des fichiers |
| 17 | « Imprime-moi le roadbook » | export_route roadbook | chemin + astuce Ctrl+P → PDF |
| 18 | « Passages techniques sur cette rando ? » | technical_passages | km, niveau, raison ; « à vérifier » le cas échéant |
| 19 | « Boucle de 25 km et 2 000 m D+ depuis un village de plaine » | generate_loop_candidates | dire honnêtement que le D+ n'est pas atteignable |
| 20 | « Fais-moi 15 km en 2 h » | set_constraints, validate_route | signaler l'incohérence (D3) au lieu d'inventer |
