"""Construit le registre des catalogues Geotrek publics (src/randoforge/engines/geotrek_catalogs.json).

Sources : la liste des Geotrek connus (wiki GeotrekCE/Geotrek-website « Liste des Geotrek connus »), dont l'adresse
d'API est lue dans la page d'accueil de chaque portail. Pour chaque catalogue on garde le nom, l'API, le nombre
de randos pédestres et l'emprise (sud, ouest, nord, est) de leurs départs, qui sert à n'interroger que les
catalogues couvrant un lieu.

    uv run python scripts/build_geotrek_catalogs.py
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from randoforge.engines.geotrek import is_walking

OUT = Path(__file__).resolve().parents[1] / "src" / "randoforge" / "engines" / "geotrek_catalogs.json"
HEADERS = {"User-Agent": "RandoForge (registre des catalogues Geotrek publics)"}
MARGIN_DEG = 0.05  # ~5 km autour des départs : une rando peut s'éloigner de son départ

# (identifiant, nom, portail). Les trois premiers gardent leur identifiant historique.
PORTALS = [
    ("ecrins", "Parc national des Écrins", "destination.ecrins-parcnational.fr"),
    ("cevennes", "Parc national des Cévennes", "destination.cevennes-parcnational.fr"),
    ("portcros", "Parc national de Port-Cros", "destination.portcros-parcnational.fr"),
    ("vanoise", "Parc national de la Vanoise", "rando.vanoise.com"),
    ("mercantour", "Parc national du Mercantour (Marittime-Mercantour)", "destination.marittimemercantour.eu"),
    ("forets", "Parc national de Forêts", "rando.forets-parcnational.fr"),
    ("guadeloupe", "Parc national de la Guadeloupe", "www.randoguadeloupe.gp"),
    ("pnr-paca", "Parcs naturels régionaux de PACA (Chemins des parcs)", "www.cheminsdesparcs.fr"),
    (
        "grands-causses-aubrac",
        "Parcs naturels régionaux des Grands Causses et de l'Aubrac",
        "rando.parc-grands-causses.fr",
    ),
    ("vercors", "Parc naturel régional du Vercors", "rando.parc-du-vercors.fr"),
    ("haut-jura", "Parc naturel régional du Haut-Jura", "randonature.parc-haut-jura.fr"),
    ("bauges", "Parc naturel régional du Massif des Bauges", "rando.parcdesbauges.com"),
    ("vosges-nord", "Parc naturel régional des Vosges du Nord", "www.randovosgesdunord.fr"),
    ("morvan", "Parc naturel régional du Morvan", "rando.parcdumorvan.org"),
    ("pilat", "Parc naturel régional du Pilat", "pilat-rando.fr"),
    ("perche", "Parc naturel régional du Perche", "rando-perche.fr"),
    ("millevaches", "Parc naturel régional de Millevaches en Limousin", "rando-millevaches.fr"),
    ("loire-anjou-touraine", "Parc naturel régional Loire-Anjou-Touraine", "rando-loireanjoutouraine.fr"),
    ("pnr-idf", "Parcs naturels régionaux d'Île-de-France", "rando.pnr-idf.fr"),
    ("hautes-alpes", "Hautes-Alpes (Alpes Rando)", "alpesrando.net"),
    ("doubs", "Doubs (Explore Doubs)", "explore.doubs.fr"),
    ("gard", "Gard (Rando Gard)", "rando.gard.fr"),
    ("jura", "Jura (Jura Outdoor)", "www.jura-outdoor.com"),
    ("haute-loire", "Haute-Loire (sports nature)", "sportsnature.hauteloire.fr"),
    ("loire-atlantique", "Loire-Atlantique", "rando.loire-atlantique.fr"),
    ("orne", "Orne (Randonnée Normandie)", "www.randonnee-normandie.com"),
    ("pas-de-calais", "Pas-de-Calais (Escapade 62)", "www.escapade62.fr"),
    ("pyrenees-atlantiques", "Pyrénées-Atlantiques (Nature 64)", "nature64.fr"),
    ("hautes-pyrenees", "Hautes-Pyrénées (Vallées de Gavarnie)", "rando.valleesdegavarnie.com"),
    ("pyrenees-orientales", "Pyrénées-Orientales (Conflent-Canigó)", "rando.tourisme-canigo.com"),
    ("tarn", "Tarn (Rando pleine nature)", "randopleinenature.tarn.fr"),
    ("var", "Var (sport nature)", "sportnature.var.fr"),
    ("cote-vermeille", "Albères - Côte Vermeille", "rando.tourisme-pyrenees-mediterranee.fr"),
    ("ales", "Alès Agglomération", "alesagglo-evasion.fr"),
    ("comminges", "Cœur et Coteaux du Comminges", "rando.coeurcoteaux-comminges.fr"),
    ("pyrenees-haut-garonnaises", "Pyrénées Haut-Garonnaises", "rando.cc-pyreneeshautgaronnaises.fr"),
    ("caux-vexin", "Inter Caux Vexin", "rando.intercauxvexin.fr"),
    ("ardeche-hermitage", "Ardèche en Hermitage", "trahce.com"),
    ("sisteronais", "Sisteronais-Buëch", "rando.sisteron-alpesprovencales.fr"),
    ("compiegne", "Compiègne-Pierrefonds", "itineraires.compiegne-pierrefonds.fr"),
    ("carcassonne", "Grand Carcassonne", "rando.grand-carcassonne-tourisme.fr"),
    ("sud-vienne", "Sud Vienne Poitou", "rando.sudviennepoitou.com"),
    ("haute-savoie-nature", "Conservatoire d'espaces naturels de Haute-Savoie", "rando.nature-haute-savoie.fr"),
    ("via-columbani", "Via Columbani", "viacolumbani.com"),
]


def api_of(portal: str) -> str | None:
    html = httpx.get(f"https://{portal}/", headers=HEADERS, timeout=30, follow_redirects=True).text
    for api in sorted(set(re.findall(r"https?://[A-Za-z0-9.\-]+(?::\d+)?/api/v2", html.replace("\\/", "/")))):
        r = httpx.get(f"{api}/trek/", params={"format": "json", "page_size": 1, "fields": "id"}, headers=HEADERS,
                      timeout=30)  # fmt: skip
        if r.status_code == 200 and "count" in r.json():
            return api
    return None


def describe(entry: tuple[str, str, str]) -> dict | None:
    cid, name, portal = entry
    try:
        api = api_of(portal)
        if not api:
            raise ValueError("API introuvable")
        practices = httpx.get(f"{api}/trek_practice/", params={"format": "json", "language": "fr"},
                              headers=HEADERS, timeout=30).json()["results"]  # fmt: skip
        walking = [p["id"] for p in practices if is_walking(p.get("name"))]
        if not walking:
            raise ValueError("aucune pratique pédestre")
        params = {"format": "json", "fields": "id,departure_geom", "page_size": 500,
                  "practices": ",".join(map(str, walking))}  # fmt: skip
        url, lats, lons, count = f"{api}/trek/", [], [], 0
        while url:
            data = httpx.get(url, params=params, headers=HEADERS, timeout=60).json()
            count = data["count"]
            for t in data["results"]:
                g = t.get("departure_geom")
                c = (g.get("coordinates") if isinstance(g, dict) else g) or None
                if c:
                    lons.append(c[0])
                    lats.append(c[1])
            url, params = data.get("next"), None  # l'URL suivante contient déjà les paramètres
        if not lats:
            raise ValueError("aucun départ localisé")
        bbox = [round(min(lats) - MARGIN_DEG, 3), round(min(lons) - MARGIN_DEG, 3),
                round(max(lats) + MARGIN_DEG, 3), round(max(lons) + MARGIN_DEG, 3)]  # fmt: skip
        return {"id": cid, "nom": name, "api": f"{api}/", "portail": f"https://{portal}/", "randos": count,
                "bbox": bbox}  # fmt: skip
    except Exception as exc:  # noqa: BLE001 — un catalogue indisponible est simplement écarté du registre
        print(f"écarté : {cid} ({portal}) — {exc}", file=sys.stderr)
        return None


def main() -> None:
    with ThreadPoolExecutor(8) as pool:
        found = [c for c in pool.map(describe, PORTALS) if c]
    seen: set[str] = set()
    catalogs = []
    for c in found:  # deux portails sur la même API (ex. Écrins) : un seul catalogue
        if c["api"] not in seen:
            seen.add(c["api"])
            catalogs.append(c)
    OUT.write_text(json.dumps(catalogs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(catalogs)} catalogues, {sum(c['randos'] for c in catalogs)} randos pédestres -> {OUT}")


if __name__ == "__main__":
    main()
