"""Ajoute à evals/reference.json deux séries de randos réelles tirées des catalogues officiels Geotrek.

- `cat-*` (mode « catalogue ») : randos de catalogues autres que les parcs nationaux d'origine ; l'agent reçoit
  le nom et le départ, tous les outils sont permis : mesure s'il retrouve et importe le tracé officiel.
- `desc-*` (mode « descriptif ») : l'agent reçoit le descriptif complet (sans chiffres) mais aucun import n'est
  permis (ni catalogue ni sentier OSM) : mesure la reconstruction d'après les lieux cités (route_via_places).

    uv run python evals/build_catalog_scenarios.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from randoforge.engines.geotrek import INSTANCES, PARKS, GeotrekReference
from randoforge.http import DAY, CachedHttp
from randoforge.storage import default_home

OUT = Path(__file__).parent / "reference.json"
LEAK = re.compile(r"\d[\d  .,]*\s*(km|kilom|m\b|mètres|h\b|heures?|min)", re.IGNORECASE)
ROUTE_TYPES = {"boucle": "boucle", "aller-retour": "aller-retour", "traversée": "traversée", "itinérance": None}

CATALOGUE_SET = ["vercors", "pyrenees-atlantiques", "pnr-paca", "doubs"]
# Descriptif : le Chemin des fileuses (absent d'OSM, raté en reconstruction sans descriptif) et trois autres.
DESCRIPTIF_SET = [("cevennes", 98959), ("vercors", None), ("hautes-pyrenees", None), ("haut-jura", None)]


def clean(text: str | None, limit: int) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = LEAK.sub("…", text)  # ni distance, ni dénivelé, ni durée : c'est ce qu'on évalue
    return re.sub(r"\s+", " ", text).strip()[:limit]


def name_of(value) -> str:
    return value if isinstance(value, str) else (value or {}).get("fr") or ""


def candidates(http: CachedHttp, ref: GeotrekReference, cid: str) -> list[dict]:
    url = INSTANCES[cid]
    types = http.request_json("GET", url.replace("/trek/", "/trek_route/"), params={"format": "json", "language": "fr"},
                              ttl_s=30 * DAY)["results"]  # fmt: skip
    kinds = {t["id"]: ROUTE_TYPES.get(name_of(t["route"]).lower()) for t in types}
    params = {"format": "json", "language": "fr", "page_size": 200, "ordering": "id",
              "practices": ",".join(map(str, ref.walking_practices(cid))),
              "fields": "id,name,departure,arrival,route,ascent,length_2d,description_teaser,description,geometry"}  # fmt: skip
    data = http.request_json("GET", url, params=params, ttl_s=30 * DAY)
    out = []
    for t in data["results"]:
        kind = kinds.get(t.get("route"))
        if (kind and 4000 <= (t.get("length_2d") or 0) <= 15000 and (t.get("ascent") or 0) >= 150
                and t.get("departure") and (t.get("geometry") or {}).get("type") == "LineString"):  # fmt: skip
            out.append({**t, "kind": kind})
    return out


def scenario(prefix: str, cid: str, t: dict, prompt: str, mode: str) -> dict:
    return {"id": f"{prefix}-{cid}-{t['id']}", "prompt": prompt, "park": cid, "geotrek_id": t["id"], "kind": t["kind"],
            "mode": mode, "official": {"length_km": round(t["length_2d"] / 1000, 2), "ascent_m": t["ascent"]},
            "has_geometry": True}  # fmt: skip


def main() -> None:
    http = CachedHttp(default_home() / "cache.sqlite")
    ref = GeotrekReference(http)
    out = [s for s in json.loads(OUT.read_text(encoding="utf-8")) if s.get("mode") not in {"catalogue", "descriptif"}]
    for cid in CATALOGUE_SET:
        cands = candidates(http, ref, cid)
        t = cands[len(cands) // 2]
        arrival = f", arrivée {t['arrival']}" if t["kind"] == "traversée" and t.get("arrival") else ""
        prompt = (f"Je voudrais faire la randonnée « {name_of(t['name'])} » ({t['kind']}), départ {t['departure']}"
                  f"{arrival}. Prépare-moi l'itinéraire.")  # fmt: skip
        out.append(scenario("cat", cid, t, prompt, "catalogue"))
    for cid, wanted in DESCRIPTIF_SET:
        cands = [t for t in candidates(http, ref, cid) if len(clean(t.get("description"), 2000)) >= 300]
        t = next((c for c in cands if c["id"] == wanted), None) or cands[len(cands) // 3]
        prompt = (f"Je voudrais refaire la randonnée « {name_of(t['name'])} » ({t['kind']}) au départ de "
                  f"{t['departure']}. Voici son descriptif : {clean(t.get('description'), 1500)} "
                  "Prépare-moi l'itinéraire.")  # fmt: skip
        out.append(scenario("desc", cid, t, prompt, "descriptif"))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in out[-8:]:
        print(f"- {s['id']} ({PARKS[s['park']]}) : {s['prompt'][:140]}… {s['official']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
