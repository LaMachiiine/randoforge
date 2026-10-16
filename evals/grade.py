"""Notation des évals : comportement de l'agent (outils, chiffres traçables, formulations) et,
pour les randos réelles, écart entre le tracé construit par l'agent et le tracé officiel.

Chaque exécution de scénario est un dossier contenant :
- `calls.jsonl` : un appel d'outil par ligne {"outil", "args", "erreur", "resultat"} ;
- `answer.md`   : la réponse finale de l'agent à l'utilisateur ;
- `home/`       : le RANDOFORGE_HOME utilisé (itinéraires créés).
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from randoforge.core.models import Route, TrackPoint
from randoforge.core.similarity import deviation, overlap_fraction
from randoforge.core.stats import compute_stats

ROUTE_TOOLS = {
    "route_between",
    "generate_loop_candidates",
    "import_gpx",
    "bailout_route",
    "import_official_trek",
    "import_hiking_route",
}
# Espaces de séparation des milliers : ASCII, insécable (U+00A0) et fine insécable (U+202F).
SPACES = " \u00a0\u202f"
# Champs de résultat qui ne sont pas des mesures (identifiants, coordonnées, liens) : exclus de la traçabilité.
NOT_MEASURES = {
    "route_id",
    "osm_id",
    "id",
    "trek_id",
    "wikidata",
    "lien",
    "wikipedia_url",
    "lat",
    "lon",
    "path",
    "files",
}
# Chiffre + unité ; « km/h » (vitesse du vent) n'est pas une distance. Un « ~ » ou « ≈ » devant marque une estimation.
NUMBER_RE = re.compile(
    r"([~≈]\s*)?(?<![\w.,])(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+(?:[.,]\d+)?)\s*(km(?!/h)|m\b|h\d{2}|h\b)",
    re.IGNORECASE,
)
FORBID_DEFAULT = [r"\b(?:est|sont)\s+autoris[ée]", r"\bautoris[ée]s?\s+(?:au|le|en)\s+bivouac"]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Grade:
    scenario: str
    checks: list[Check] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def score(self) -> float:
        return sum(c.ok for c in self.checks) / len(self.checks) if self.checks else 0.0


def load_run(run_dir: Path) -> tuple[list[dict], str]:
    calls_file = run_dir / "calls.jsonl"
    calls = (
        [json.loads(line) for line in calls_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if calls_file.exists()
        else []
    )
    answer = (run_dir / "answer.md").read_text(encoding="utf-8") if (run_dir / "answer.md").exists() else ""
    return calls, answer


def created_routes(calls: list[dict], exclude: frozenset[str] = frozenset()) -> list[str]:
    ids = []
    for c in calls:
        if c["outil"] not in ROUTE_TOOLS - exclude or c.get("erreur"):
            continue
        res = c.get("resultat") or {}
        if "route_id" in res:
            ids.append(res["route_id"])
        for cand in res.get("candidates", []):
            ids.append(cand["route"]["route_id"])
    return ids


def _numbers_in_results(calls: list[dict]) -> tuple[list[float], str]:
    def measures(value):
        if isinstance(value, dict):
            return {k: measures(v) for k, v in value.items() if k not in NOT_MEASURES}
        if isinstance(value, list):
            return [measures(v) for v in value]
        return value

    blob = json.dumps([measures(c.get("resultat")) for c in calls], ensure_ascii=False)
    # Valeurs absolues : « 8,2 km plus courte » reprend un écart signé « -8.24 » de l'outil.
    values = [abs(float(x)) for x in re.findall(r"-?\d+(?:\.\d+)?", blob)]
    return values, blob


def _num(raw: str) -> float:
    return float("".join(ch for ch in raw if ch not in SPACES).replace(",", "."))


def traceable_numbers(answer: str, calls: list[dict], prompt: str) -> tuple[float, list[str]]:
    """Part des chiffres annoncés (km, m, durées) retrouvés dans les résultats d'outils."""
    values, blob = _numbers_in_results(calls)
    # Nombres entiers du prompt (« 2 000 m » → 2000) : comparés en valeur, pas en sous-chaîne.
    given = {_num(m) for m in re.findall(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+(?:[.,]\d+)?", prompt)}
    untraced, total = [], 0
    for approx, raw, unit in NUMBER_RE.findall(answer):
        if approx:
            continue  # estimation annoncée comme telle (≈), autorisée par le skill
        token = f"{raw}{unit}"
        num = _num(raw)
        if num in given:
            continue  # chiffre donné par l'utilisateur
        unit = unit.lower()
        if unit.startswith("h") and len(unit) > 1:  # durée « 4h37 »
            total += 1
            h, mm = int(num), unit[1:]
            # « 4h37 » (durée) ou « 19h00 » = « 19:00 » (heure) : les deux écritures comptent.
            if not any(form in blob for form in (f"{h}h{mm}", f"{h:02d}:{mm}", f"{h}:{mm}")):
                untraced.append(token)
            continue
        if unit == "h" or num < 1:
            continue  # heures rondes et petites valeurs : trop ambiguës
        total += 1
        tol = 0.15 if unit == "km" else max(5.0, 0.02 * num)
        if not re.search(r"[.,]", raw):
            tol = max(tol, 0.5 if unit == "km" else 5.0)  # entier = valeur d'outil arrondie (« 48 km » pour 47,8)
        if not any(abs(v - num) <= tol for v in values) and not (
            unit == "km" and any(abs(v / 1000 - num) <= tol for v in values)
        ):
            untraced.append(token)
    return (1 - len(untraced) / total if total else 1.0), untraced


def _same(actual, expected) -> bool:
    """Égalité tolérante : « 15:00 » = « 15:00:00 »."""
    if isinstance(actual, str) and isinstance(expected, str) and ":" in expected:
        return actual.ljust(8, ":").replace("::", ":00")[:5] == expected[:5]
    return actual == expected


def grade_behaviour(scenario: dict, run_dir: Path) -> Grade:
    calls, answer = load_run(run_dir)
    g = Grade(scenario["id"])
    called = [c["outil"] for c in calls]
    used = list(called)  # outils appelés + analyses faites côté serveur par un outil composite
    if any((c.get("resultat") or {}).get("validation_status") for c in calls if c["outil"] == "weather_forecast"):
        used += ["validate_route"]  # weather_forecast valide l'itinéraire lui-même (côté serveur)
    if "analyze_route" in used:  # outil composite : vaut les quatre analyses qu'il lance
        used += ["validate_route", "annotate_route", "technical_passages", "route_areas"]
    g.metrics["outils"] = called
    if not answer.strip():
        g.checks.append(Check("réponse", False, "pas de réponse finale"))
        return g
    for group in scenario.get("tools", []):
        options = group.split("|")
        g.checks.append(
            Check(
                f"outil {group}",
                any(o in used for o in options),
                "" if any(o in used for o in options) else "non appelé",
            )
        )
    for pattern in scenario.get("mentions", []):
        found = re.search(pattern, answer, re.IGNORECASE)
        g.checks.append(Check(f"mentionne /{pattern}/", bool(found)))
    for pattern in FORBID_DEFAULT + scenario.get("forbid", []):
        found = re.search(pattern, answer, re.IGNORECASE)
        g.checks.append(Check(f"évite /{pattern}/", not found, found.group(0) if found else ""))
    if expected := scenario.get("constraints"):
        args = [c["args"] for c in calls if c["outil"] == "set_constraints"]
        ok = any(all(_same(a.get(k), v) for k, v in expected.items()) for a in args)
        g.checks.append(Check(f"contraintes {expected}", ok))
    if set(used) & ROUTE_TOOLS and scenario.get("validate", True):
        g.checks.append(Check("validate_route avant de répondre", "validate_route" in used))
    ratio, untraced = traceable_numbers(answer, calls, scenario["prompt"])
    g.metrics["chiffres_tracables"] = round(ratio, 2)
    g.checks.append(Check("chiffres traçables (≥ 90 %)", ratio >= 0.9, ", ".join(untraced[:6])))
    if target := scenario.get("route_km"):
        km, tol = target
        dists = [c["resultat"]["stats"]["distance_km"] for c in calls if c["outil"] in ROUTE_TOOLS and not c.get("erreur")
                 and (c.get("resultat") or {}).get("stats")]  # fmt: skip
        dists += [
            cand["route"]["stats"]["distance_km"]
            for c in calls
            for cand in (c.get("resultat") or {}).get("candidates", [])
        ]
        ok = any(abs(d - km) / km <= tol for d in dists)
        g.checks.append(Check(f"un tracé à {km} km ± {tol:.0%}", ok, f"distances : {dists[:5]}"))
    return g


def grade_reference(scenario: dict, run_dir: Path, official: list[tuple[float, float, float | None]]) -> Grade:
    """Rando réelle : le tracé final de l'agent est comparé au tracé officiel du parc."""
    calls, answer = load_run(run_dir)
    g = grade_behaviour({**scenario, "tools": ["route_between|generate_loop_candidates|import_hiking_route"]}, run_dir)
    # Le tracé présenté : celui exporté en dernier ; à défaut, le dernier construit, hors itinéraire de repli
    # (demandé en fin de démarche par le skill). Les tracés construits pour comparer ne comptent pas.
    bailouts = set(created_routes([c for c in calls if c["outil"] == "bailout_route"]))
    exported = [
        c["args"].get("route_id")
        for c in calls
        if c["outil"] == "export_route" and not c.get("erreur") and c["args"].get("route_id") not in bailouts
    ]
    ids = created_routes(calls, exclude=frozenset({"bailout_route"})) + [r for r in exported if r]
    routes_dir = run_dir / "home" / "routes"
    agent_route = None
    for rid in reversed(ids):  # le dernier tracé construit est celui présenté
        f = routes_dir / rid / "route.json"
        if f.exists():
            agent_route = Route.model_validate_json(f.read_text(encoding="utf-8"))
            break
    if agent_route is None:
        g.checks.append(Check("tracé construit", False, "aucun tracé retrouvé"))
        return g
    ref_pts = [TrackPoint(lat=a, lon=b, ele=z) for a, b, z in official]
    cover = overlap_fraction(ref_pts, agent_route.points, 50.0)  # part du tracé officiel suivie par l'agent
    mean_dev, _, _ = deviation(agent_route.points, ref_pts)
    ref_stats, _ = compute_stats([TrackPoint(lat=a, lon=b) for a, b, _ in official])
    dist_err = (agent_route.stats.distance_km - scenario["official"]["length_km"]) / scenario["official"]["length_km"]
    if agent_route.stats.d_plus_m is None:
        g.checks.append(Check("D+ calculé", False, "altitudes manquantes"))
        return g
    dplus_err = (agent_route.stats.d_plus_m - scenario["official"]["ascent_m"]) / scenario["official"]["ascent_m"]
    g.metrics.update({"recouvrement": round(cover, 2), "ecart_moyen_m": round(mean_dev), "distance_agent_km": agent_route.stats.distance_km,
                      "distance_officielle_km": scenario["official"]["length_km"], "ecart_distance": round(dist_err, 3),
                      "d_plus_agent": agent_route.stats.d_plus_m, "d_plus_officiel": scenario["official"]["ascent_m"],
                      "ecart_d_plus": round(dplus_err, 3), "km_officiel_recalcule": ref_stats.distance_km})  # fmt: skip
    g.checks.append(Check("suit le tracé officiel (≥ 60 % à moins de 50 m)", cover >= 0.6, f"{cover:.0%}"))
    g.checks.append(Check("distance à ± 20 %", abs(dist_err) <= 0.2, f"{dist_err:+.0%}"))
    g.checks.append(Check("D+ à ± 25 %", abs(dplus_err) <= 0.25, f"{dplus_err:+.0%}"))
    return g


def report(grades: list[Grade], title: str) -> str:
    lines = [f"# {title}", "", f"**{sum(g.passed for g in grades)} / {len(grades)} scénarios réussis** · "
             f"score moyen {statistics.mean(g.score for g in grades):.0%}", "",
             "| Scénario | Réussi | Score | Échecs | Mesures |", "|---|---|---|---|---|"]  # fmt: skip
    for g in grades:
        fails = "; ".join(f"{c.name}" + (f" ({c.detail})" if c.detail else "") for c in g.checks if not c.ok) or "—"
        metrics = ", ".join(f"{k}={v}" for k, v in g.metrics.items() if k != "outils")
        lines.append(f"| {g.scenario} | {'✅' if g.passed else '❌'} | {g.score:.0%} | {fails} | {metrics} |")
    return "\n".join(lines) + "\n"
