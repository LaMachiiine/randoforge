"""Construit les scénarios « randos réelles » à partir des itinéraires officiels des parcs nationaux.

    uv run python evals/build_reference.py [par_parc]

L'agent reçoit ce qu'un randonneur lirait (nom, type, départ, arrivée, descriptif) mais ni le tracé
ni les chiffres officiels ; la notation compare ensuite son tracé au tracé officiel.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from randoforge.engines.geotrek import INSTANCES, GeotrekReference
from randoforge.http import DAY, CachedHttp
from randoforge.storage import default_home

OUT = Path(__file__).parent / "reference.json"
PARKS = {"ecrins": "Parc national des Écrins", "cevennes": "Parc national des Cévennes"}
ROUTE_TYPES = {"Boucle": "boucle", "Aller-retour": "aller-retour", "Traversée": "traversée"}
LEAK = re.compile(r"\d[\d  .,]*\s*(km|kilom|m\b|mètres|h\b|heures?|min)", re.IGNORECASE)


def clean(text: str | None) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = LEAK.sub("…", text)  # pas de distance, de dénivelé ni de durée : c'est ce qu'on évalue
    return re.sub(r"\s+", " ", text).strip()[:400]


def main(per_park: int) -> None:
    http = CachedHttp(default_home() / "cache.sqlite")
    ref = GeotrekReference(http)
    scenarios = []
    for park in PARKS:
        url = INSTANCES[park]
        types = http.request_json("GET", url.replace("/trek/", "/trek_route/"), params={"format": "json", "language": "fr"},
                                  ttl_s=30 * DAY)["results"]  # fmt: skip
        type_names = {t["id"]: t["route"] for t in types}
        params = {"format": "json", "language": "fr", "page_size": 100, "ordering": "id",
                  "practices": ",".join(map(str, ref.walking_practices(park))),
                  "fields": "id,name,departure,arrival,route,ascent,length_2d,description_teaser"}  # fmt: skip
        data = http.request_json("GET", url, params=params, ttl_s=30 * DAY)
        candidates = [
            t for t in data["results"]
            if type_names.get(t.get("route")) in ROUTE_TYPES and 4000 <= (t.get("length_2d") or 0) <= 15000
            and (t.get("ascent") or 0) >= 150 and t.get("departure")
        ]  # fmt: skip
        step = max(1, len(candidates) // per_park)
        chosen = candidates[::step][:per_park]
        geoms = {t.id: t for t in ref.treks(park, 400)}
        for t in chosen:
            kind = ROUTE_TYPES[type_names[t["route"]]]
            name = t["name"] if isinstance(t["name"], str) else t["name"].get("fr")
            arrival = f", arrivée {t['arrival']}" if kind == "traversée" and t.get("arrival") else ""
            prompt = (f"Je voudrais faire la randonnée « {name} » ({kind}) dans le {PARKS[park]} : départ {t['departure']}"
                      f"{arrival}. {clean(t.get('description_teaser'))} Prépare-moi l'itinéraire.")  # fmt: skip
            scenarios.append({
                "id": f"ref-{park}-{t['id']}", "prompt": prompt, "park": park, "geotrek_id": t["id"], "kind": kind,
                "official": {"length_km": round(t["length_2d"] / 1000, 2), "ascent_m": t["ascent"]},
                "has_geometry": t["id"] in geoms,
            })  # fmt: skip
    OUT.write_text(json.dumps(scenarios, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(scenarios)} scénarios écrits dans {OUT}")
    for s in scenarios:
        print(f"- {s['id']} : {s['prompt'][:130]}… [{s['official']}] géométrie={s['has_geometry']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 4)
