"""Appeler les outils RandoForge en ligne de commande (évals, débogage, scripts).

    uv run python scripts/rf.py list                      # outils, descriptions et paramètres
    uv run python scripts/rf.py call <outil> '<json>'     # appel ; résultat JSON sur la sortie standard

Chaque appel est ajouté au journal RF_LOG (une ligne JSON par appel) si la variable est définie.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time

from mcp import Client

from randoforge.server import build_server


async def main(argv: list[str]) -> int:
    async with Client(build_server()) as client:
        if argv[:1] == ["list"]:
            for t in (await client.list_tools()).tools:
                print(
                    f"## {t.name}\n{t.description}\nParamètres : {json.dumps(t.input_schema.get('properties', {}), ensure_ascii=False)}\n"
                )
            return 0
        if len(argv) < 2 or argv[0] != "call":
            print(__doc__)
            return 2
        tool, args = argv[1], json.loads(argv[2]) if len(argv) > 2 else {}
        t0 = time.time()
        res = await client.call_tool(tool, args)
        out = {"erreur": res.content[0].text} if res.is_error else res.structured_content
        if log := os.environ.get("RF_LOG"):
            with open(log, "a", encoding="utf-8") as f:
                entry = {"outil": tool, "args": args, "erreur": res.is_error, "duree_s": round(time.time() - t0, 1),
                         "resultat": out}  # fmt: skip
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return 1 if res.is_error else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    logging.disable(logging.WARNING)
    sys.exit(asyncio.run(main(sys.argv[1:])))
