"""Lance les évals avec de vrais agents Claude Code branchés sur le serveur RandoForge, puis les note.

    uv run python evals/run.py [--kind all|behaviour|reference] [--only ID ...] [--workers 3] [--model sonnet]

Chaque agent : `claude -p` non interactif, outils intégrés désactivés (ni web ni shell), seuls les outils
MCP RandoForge autorisés, skill `planifier-rando` en consigne système. Résultats dans evals/runs/<horodatage>/
et rapport copié dans docs/30 - Claude/Résultats des évals.md. Prérequis : `claude auth login`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path

from grade import Check, Grade, grade_behaviour, grade_reference, load_run, report

from randoforge.engines.geotrek import GeotrekReference
from randoforge.http import CachedHttp, HttpError
from randoforge.storage import default_home

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
SKILL = ROOT / "skills" / "planifier-rando" / "SKILL.md"
DOC = ROOT / "docs" / "30 - Claude" / "Résultats des évals.md"
TOOL_PREFIX = "mcp__randoforge__"
AGENT_TIMEOUT_S = 2400  # les scénarios les plus lourds (itinérance, boucles) dépassent 20 min sur Overpass public


def claude_command() -> list[str]:
    """Commande Claude Code. Sous Windows, le lanceur npm `claude.cmd` coupe les arguments aux retours à la
    ligne (la consigne système en contient) : on appelle directement node + cli.js."""
    exe = shutil.which("claude")
    if not exe:
        sys.exit("Commande `claude` introuvable : installer Claude Code puis `claude auth login`.")
    cli = Path(exe).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    node = shutil.which("node") or str(Path("C:/Program Files/nodejs/node.exe"))
    return [node, str(cli)] if cli.exists() else [exe]


def system_prompt() -> str:
    today = date.today()
    return (
        SKILL.read_text(encoding="utf-8").split("---", 2)[-1]
        + f"\n\nContexte : nous sommes le {today:%A %d %B %Y} ({today.isoformat()}). Tu réponds en français. "
        "Tu ne peux pas poser de question à l'utilisateur dans cette conversation : quand une information manque, "
        "choisis une valeur par défaut raisonnable et dis-la. Utilise uniquement les outils RandoForge."
    )


def to_calls(transcript: Path) -> tuple[list[dict], str, float, int, dict]:
    """Transcription stream-json → (appels d'outils avec résultats, réponse finale, coût $, tours)."""
    pending: dict[str, dict] = {}
    calls, answer, cost, turns = [], "", 0.0, 0
    tokens = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}
    for line in transcript.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("{"):
            continue
        e = json.loads(line)
        if e.get("type") == "assistant":
            for c in e["message"]["content"]:
                if c.get("type") == "tool_use" and c["name"].startswith(TOOL_PREFIX):
                    pending[c["id"]] = {"outil": c["name"][len(TOOL_PREFIX) :], "args": c.get("input", {})}
        elif e.get("type") == "user":
            for c in e["message"].get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in pending:
                    call = pending.pop(c["tool_use_id"])
                    text = c.get("content")
                    if isinstance(text, list):
                        text = "".join(x.get("text", "") for x in text if isinstance(x, dict))
                    try:
                        result = json.loads(text)
                    except (TypeError, ValueError):
                        result = {"texte": text}
                    calls.append(
                        {**call, "erreur": bool(c.get("is_error")), "resultat": result, "taille": len(text or "")}
                    )
        elif e.get("type") == "result":
            answer += (e.get("result") or "") + "\n\n"
            cost += e.get("total_cost_usd") or 0
            turns += e.get("num_turns") or 0
            for k in tokens:
                tokens[k] += (e.get("usage") or {}).get(k) or 0
    return calls, answer.strip(), cost, turns, tokens


# Randos réelles : outils interdits selon ce que le scénario mesure (le tracé officiel noté ne doit pas être importé,
# sauf en mode « catalogue » où c'est justement ce qu'on mesure).
FORBIDDEN_BY_MODE = {
    "reconstruction": ["import_official_trek", "find_official_treks"],
    "descriptif": ["import_official_trek", "find_official_treks", "import_hiking_route"],
    "catalogue": [],
}


async def kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Arrête l'agent et ses sous-processus (sous Windows, `claude.cmd` lance node, qui survivrait à cmd.exe)."""
    if sys.platform == "win32":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(proc.pid),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        await killer.wait()
    else:
        proc.kill()
    await proc.wait()


async def run_agent(
    scenario: dict, run_dir: Path, cache: Path | None, model: str | None, sem: asyncio.Semaphore
) -> dict:
    async with sem:
        home = run_dir / "home"
        home.mkdir(parents=True, exist_ok=True)
        (run_dir / "vault").mkdir(exist_ok=True)
        if cache and cache.exists():
            shutil.copyfile(cache, home / "cache.sqlite")  # même données, réponses plus rapides
        mcp = {"mcpServers": {"randoforge": {"command": "uv", "args": ["run", "--directory", str(ROOT), "randoforge"],
                                             "env": {"RANDOFORGE_HOME": str(home)}}}}  # fmt: skip
        (run_dir / "mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
        # --setting-sources project : ni les plugins ni les hooks personnels de l'utilisateur ne s'invitent dans l'éval.
        base = [*claude_command(), "--mcp-config", str(run_dir / "mcp.json"), "--strict-mcp-config", "--setting-sources",
                "project", "--allowedTools", "mcp__randoforge",
                "--tools", "", "--output-format", "stream-json", "--verbose", "--max-turns", "40",
                "--append-system-prompt", system_prompt()]  # fmt: skip
        if model:
            base += ["--model", model]
        if (
            forbidden := FORBIDDEN_BY_MODE.get(scenario.get("mode", "reconstruction"))
            if scenario.get("official")
            else None
        ):
            base += ["--disallowedTools", ",".join(f"mcp__randoforge__{t}" for t in forbidden)]
        turns = scenario.get("turns") or [scenario["prompt"]]
        fill = {"fixtures": str(EVALS / "fixtures").replace("\\", "/"), "run_dir": str(run_dir).replace("\\", "/")}
        transcript = run_dir / "transcript.jsonl"
        session = None
        t0 = time.time()
        err_file = run_dir / "stderr.txt"
        with transcript.open("ab") as out, err_file.open("ab") as err:
            for message in turns:
                cmd = [*base, "-p", message.format(**fill)] + (["--resume", session] if session else [])
                start = transcript.stat().st_size
                # stdin fermé : sinon `claude -p` lancé en arrière-plan attend une entrée qui ne vient jamais.
                # stdout écrit directement dans le fichier : rien n'est perdu si l'agent doit être arrêté.
                proc = await asyncio.create_subprocess_exec(
                    *cmd, cwd=run_dir, stdin=asyncio.subprocess.DEVNULL, stdout=out, stderr=err
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=AGENT_TIMEOUT_S)
                except TimeoutError:
                    await kill_tree(proc)
                    err.write(f"\nAgent arrêté après {AGENT_TIMEOUT_S} s\n".encode())
                out.flush()
                with transcript.open(encoding="utf-8", errors="replace") as f:
                    f.seek(start)
                    for line in f:
                        if '"session_id"' in line and line.startswith("{"):
                            session = json.loads(line).get("session_id") or session
        if err_file.stat().st_size == 0:
            err_file.unlink()
        calls, answer, cost, n_turns, tokens = to_calls(transcript)
        (run_dir / "calls.jsonl").write_text(
            "\n".join(json.dumps(c, ensure_ascii=False, default=str) for c in calls), encoding="utf-8"
        )
        (run_dir / "answer.md").write_text(answer, encoding="utf-8")
        sizes: dict[str, int] = {}
        for c in calls:
            sizes[c["outil"]] = sizes.get(c["outil"], 0) + c.get("taille", 0)
        meta = {
            "id": scenario["id"],
            "cout_usd": round(cost, 4),
            "tours": n_turns,
            "duree_s": round(time.time() - t0),
            "jetons": tokens,
            "taille_resultats_par_outil": sizes,
        }
        print(f"  ✓ {scenario['id']} : {len(calls)} appels, {meta['duree_s']} s, {meta['cout_usd']} $", flush=True)
        return meta


def grade_all(scenarios: list[dict], out: Path) -> list[Grade]:
    ref = GeotrekReference(CachedHttp(default_home() / "cache.sqlite"))
    grades = []
    for s in scenarios:
        run_dir = out / s["id"]
        if "geotrek_id" in s:
            try:
                official = ref.trek(s["park"], s["geotrek_id"]).coords
            except (ValueError, HttpError) as exc:
                g = Grade(s["id"])
                g.checks.append(Check("référence officielle disponible", False, str(exc)))
                grades.append(g)
                continue
            g = grade_reference(s, run_dir, official)
        else:
            g = grade_behaviour({**s, "prompt": " ".join(s.get("turns") or [s["prompt"]])}, run_dir)
        grades.append(g)
    return grades


def usage_section(metas: list[dict]) -> str:
    """Consommation : jetons par scénario et outils dont les réponses pèsent le plus (à optimiser en priorité)."""
    if not metas or "jetons" not in metas[0]:
        return ""
    lines = ["", "## Consommation", "", "| Scénario | Coût estimé | Jetons entrée (dont cache) | Jetons sortie | Tours |",
             "|---|---|---|---|---|"]  # fmt: skip
    for m in metas:
        t = m["jetons"]
        total_in = t["input_tokens"] + t["cache_creation_input_tokens"] + t["cache_read_input_tokens"]
        lines.append(f"| {m['id']} | {m['cout_usd']:.2f} $ | {total_in:,} ({t['cache_read_input_tokens']:,}) | "
                     f"{t['output_tokens']:,} | {m['tours']} |")  # fmt: skip
    sizes: dict[str, int] = {}
    for m in metas:
        for tool, n in m.get("taille_resultats_par_outil", {}).items():
            sizes[tool] = sizes.get(tool, 0) + n
    lines += ["", "Taille cumulée des réponses d'outils (caractères, environ 4 par jeton) :", ""]
    lines += [f"- `{tool}` : {n:,}" for tool, n in sorted(sizes.items(), key=lambda kv: -kv[1])]
    return "\n".join(lines) + "\n"


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--kind", choices=["all", "behaviour", "reference"], default="all")
    p.add_argument("--only", nargs="*")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--model")
    p.add_argument("--grade-only", type=Path, help="Re-noter un dossier de résultats existant")
    p.add_argument("--out", type=Path, help="Dossier de résultats existant à compléter (relancer des scénarios ratés)")
    args = p.parse_args()

    scenarios = []
    if args.kind in {"all", "behaviour"}:
        scenarios += json.loads((EVALS / "scenarios.json").read_text(encoding="utf-8"))
    if args.kind in {"all", "reference"}:
        scenarios += json.loads((EVALS / "reference.json").read_text(encoding="utf-8"))
    if args.only:
        scenarios = [s for s in scenarios if any(s["id"].startswith(o) for o in args.only)]

    out = (args.grade_only or args.out or EVALS / "runs" / datetime.now().strftime("%Y-%m-%d_%H%M")).resolve()
    metas = []
    if not args.grade_only:
        claude_command()
        print(f"{len(scenarios)} scénarios → {out}")
        sem = asyncio.Semaphore(args.workers)
        cache = default_home() / "cache.sqlite"
        for s in scenarios:  # relance propre d'un scénario
            shutil.rmtree(out / s["id"], ignore_errors=True)
        metas = await asyncio.gather(*(run_agent(s, out / s["id"], cache, args.model, sem) for s in scenarios))
        if args.out:  # on complète les mesures existantes
            ids = {m["id"] for m in metas}
            previous = (
                json.loads((out / "meta.json").read_text(encoding="utf-8")) if (out / "meta.json").exists() else []
            )
            metas = [m for m in previous if m["id"] not in ids] + metas
            known = {m["id"] for m in metas}
            # Scénarios d'une série interrompue sans meta.json : mesures reconstruites depuis la transcription.
            for d in sorted(p for p in out.iterdir() if p.is_dir() and p.name not in known):
                if (d / "transcript.jsonl").exists():
                    calls, _, cost, n_turns, tokens = to_calls(d / "transcript.jsonl")
                    sizes: dict[str, int] = {}
                    for c in calls:
                        sizes[c["outil"]] = sizes.get(c["outil"], 0) + c.get("taille", 0)
                    metas.append({"id": d.name, "cout_usd": round(cost, 4), "tours": n_turns, "duree_s": None,
                                  "jetons": tokens, "taille_resultats_par_outil": sizes})  # fmt: skip
        (out / "meta.json").write_text(json.dumps(metas, ensure_ascii=False, indent=1), encoding="utf-8")
    elif (out / "meta.json").exists():
        metas = json.loads((out / "meta.json").read_text(encoding="utf-8"))

    if args.out:  # noter tout le dossier, pas seulement les scénarios relancés
        all_scen = json.loads((EVALS / "scenarios.json").read_text(encoding="utf-8"))
        all_scen += json.loads((EVALS / "reference.json").read_text(encoding="utf-8"))
        scenarios = [s for s in all_scen if (out / s["id"]).exists()]
    grades = grade_all(scenarios, out)
    cost = sum(m["cout_usd"] for m in metas)
    title = f"Résultats des évals — {out.name}"
    body = report(grades, title)
    body += f"\nAgents : Claude Code `claude -p` ({args.model or 'modèle par défaut'}), outils RandoForge uniquement. Coût total : {cost:.2f} $.\n"
    body += usage_section(metas)
    body += "\n## Réponses des agents\n\n" + "\n".join(
        f"<details><summary>{g.scenario}</summary>\n\n{load_run(out / g.scenario)[1] or '(pas de réponse)'}\n\n"
        f"Outils : {', '.join(g.metrics.get('outils', []))}\n</details>\n"
        for g in grades
    )
    (out / "report.md").write_text(body, encoding="utf-8")
    DOC.write_text("---\ntags: [claude, evals]\n---\n" + body, encoding="utf-8")
    print(report(grades, title))
    print(f"Rapport : {out / 'report.md'} (copié dans {DOC})")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(EVALS))
    asyncio.run(main())
