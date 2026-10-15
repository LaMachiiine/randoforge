"""Calibration du dénivelé sur un jeu de traces de référence (réseau requis pour le MNT).

    uv run python scripts/calibrate.py dossier_gpx [references.csv]

Pour chaque GPX du dossier, compare :
- le D+ de la trace elle-même (altimètre de la montre),
- le D+ recalculé sur le MNT par RandoForge,
- et, si `references.csv` est fourni (colonnes `fichier;d_plus`), la valeur de référence (topo-guide).
Sert à ajuster les paramètres de docs/10 - Architecture/Calcul du dénivelé.md.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import sys
from pathlib import Path

from mcp import Client

from randoforge.server import build_server


async def main(folder: Path, refs: dict[str, float]) -> None:
    rows = []
    async with Client(build_server()) as c:
        for gpx in sorted(folder.glob("*.gpx")):
            res = {}
            for mode in ("file", "dem"):
                r = await c.call_tool("import_gpx", {"path": str(gpx), "elevation": mode})
                res[mode] = None if r.is_error else r.structured_content["stats"]
            if not res["dem"]:
                print(f"!! {gpx.name} : import impossible")
                continue
            ref = refs.get(gpx.name)
            rows.append(
                (
                    gpx.name,
                    res["dem"]["distance_km"],
                    res["file"] and res["file"]["d_plus_m"],
                    res["dem"]["d_plus_m"],
                    ref,
                )
            )
    print(f"{'Trace':30} {'km':>6} {'D+ GPX':>7} {'D+ MNT':>7} {'D+ réf':>7} {'écart':>7}")
    errors = []
    for name, km, dfile, ddem, ref in rows:
        base = ref or dfile
        gap = f"{100 * (ddem - base) / base:+.1f} %" if base else ""
        if base:
            errors.append(abs(ddem - base) / base)
        print(f"{name[:30]:30} {km:6.1f} {dfile or '':>7} {ddem:>7} {ref or '':>7} {gap:>7}")
    if errors:
        print(f"\nÉcart moyen absolu : {100 * sum(errors) / len(errors):.1f} % (cible < 5 %)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    refs = {}
    if len(sys.argv) > 2:
        with open(sys.argv[2], encoding="utf-8") as f:
            refs = {r["fichier"]: float(r["d_plus"]) for r in csv.DictReader(f, delimiter=";")}
    asyncio.run(main(Path(sys.argv[1]), refs))
