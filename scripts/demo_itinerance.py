"""Scénario réel complet (réseau requis) : traversée des Hauts-Plateaux du Vercors sur 2 jours.

    uv run python scripts/demo_itinerance.py [dossier_de_sortie]

Affiche le résultat de chaque outil ; sert de démonstration et de test manuel de bout en bout.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

from mcp import Client

from randoforge.server import build_server


async def main(out: Path) -> None:
    async with Client(build_server()) as c:

        async def call(name: str, args: dict) -> dict | None:
            t = time.time()
            r = await c.call_tool(name, args)
            if r.is_error:
                print(f"!! {name} : {r.content[0].text}")
                return None
            print(f"-- {name} ({time.time() - t:.1f} s)")
            return r.structured_content

        places = {}
        for q in ("Corrençon-en-Vercors", "Cabane de Pré Peyret", "Gresse-en-Vercors"):
            res = await call("geocode", {"query": q, "country": "fr", "limit": 1})
            places[q] = res["places"][0]
            print(f"   {q} → {places[q]['lat']:.4f}, {places[q]['lon']:.4f} ({places[q]['type']})")

        wps = [{"lat": p["lat"], "lon": p["lon"]} for p in places.values()]
        r = await call("route_between", {"waypoints": wps, "name": "Traversée des Hauts-Plateaux"})
        rid = r["route_id"]
        s = r["stats"]
        print(
            f"   {s['distance_km']} km, D+ {s['d_plus_m']} m, D- {s['d_minus_m']} m, {s['duration_label']}, {s['elevation_source']}"
        )

        day = date.today() + timedelta(days=3)
        await call("set_constraints", {"route_id": rid, "with_dog": True, "date": day.isoformat(), "start_time": "08:00",
                                       "max_duration_h": 7})  # fmt: skip

        res = await call("annotate_route", {"route_id": rid})
        print(
            f"   {len(res['pois'])} points notables ; décrits : {sum(1 for p in res['pois'] if p.get('description'))}"
        )
        res = await call("technical_passages", {"route_id": rid})
        print(f"   {len(res['passages'])} passages techniques, niveau max {res['niveau_max']}")
        res = await call("route_areas", {"route_id": rid})
        for z in res["zones"]:
            print(
                f"   zone : {z['kind']} « {z['nom']} » km {z['km_debut']}–{z['km_fin']}, chiens {z['chiens']}, bivouac {z['bivouac']}"
            )
        res = await call("data_quality", {"route_id": rid})
        if res:
            q = res["qualite"]
            print(
                f"   confiance {q['niveau']} ({q['score']}), sur chemin {q['sur_chemin_pct']} %, balisé {res['balise_pct']} %"
            )
        res = await call("weather_forecast", {"route_id": rid})
        if res:
            print(f"   météo {res['date']} {res['heures']} : {res['alertes'] or 'pas d alerte'}")
        res = await call("find_bivouac_spots", {"route_id": rid})
        if res:
            by = {}
            for b in res["emplacements"]:
                by[b["source"]] = by.get(b["source"], 0) + 1
            print(f"   {len(res['emplacements'])} emplacements : {by}")
        # Sans nombre de jours : le minimum compatible avec la durée max enregistrée (7 h)
        res = await call("plan_stages", {"route_id": rid})
        if res:
            for st in res["etapes"]:
                print(
                    f"   jour {st['jour']} : {st['distance_km']} km, D+ {st['d_plus_m']} m, {st['duree']} → {st['arrivee']} ({st['arrivee_type']})"
                )
            print(f"   notes : {res['notes']}")
        res = await call("validate_route", {"route_id": rid})
        print(f"   statut {res['status']}")
        for ch in res["checks"]:
            if ch["level"] != "info":
                print(f"     {ch['id']} {ch['level']} {ch['km']} {ch['message'][:110]}")
        res = await call("bailout_route", {"route_id": rid, "at_km": 10, "to": "depart"})
        if res:
            print(f"   repli : {res['stats']['distance_km']} km, D+ {res['stats']['d_plus_m']} m")
        res = await call("find_hiking_routes", {"lat": wps[0]["lat"], "lon": wps[0]["lon"], "radius_km": 3, "limit": 5})
        for h in res["routes"]:
            print(f"   sentier {h['reseau']} : {h['ref']} {h['nom']}")
        vault = out / "vault"
        vault.mkdir(parents=True, exist_ok=True)
        res = await call(
            "export_route", {"route_id": rid, "formats": ["gpx", "md", "html", "roadbook"], "vault_dir": str(vault)}
        )
        for k, v in res["files"].items():
            print(f"   {k}: {v}")
        await call("mark_done", {"route_id": rid, "notes": "démo"})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())))
