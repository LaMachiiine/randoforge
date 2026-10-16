"""Choix des lieux d'un descriptif parmi leurs homonymes : la suite la plus courte dans l'ordre de marche."""

from __future__ import annotations

import math

LatLon = tuple[float, float]


def _km(a: LatLon, b: LatLon) -> float:
    """Distance approchée (km), suffisante pour comparer des candidats proches les uns des autres."""
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    return 6371.0 * math.hypot(dlat, dlon)


def best_sequence(start: LatLon, candidates: list[list[LatLon]], finish: LatLon | None) -> list[int]:
    """Indice du candidat retenu pour chaque lieu (chaque liste non vide), dans l'ordre donné, minimisant la
    longueur à vol d'oiseau départ → lieux → `finish` (le départ pour une boucle, l'arrivée, ou None).

    Un homonyme éloigné allonge ce parcours : il est écarté au profit du lieu cohérent avec ses voisins
    (programmation dynamique, coût en O(lieux × candidats²)).
    """
    if not candidates:
        return []
    cost = [_km(start, c) for c in candidates[0]]
    back: list[list[int]] = []
    for prev, cur in zip(candidates, candidates[1:], strict=False):
        step, links = [], []
        for c in cur:
            j = min(range(len(prev)), key=lambda k, c=c: cost[k] + _km(prev[k], c))
            step.append(cost[j] + _km(prev[j], c))
            links.append(j)
        cost, back = step, [*back, links]
    if finish is not None:
        cost = [v + _km(c, finish) for v, c in zip(cost, candidates[-1], strict=True)]
    i = min(range(len(cost)), key=cost.__getitem__)
    chosen = [i]
    for links in reversed(back):
        i = links[i]
        chosen.append(i)
    return chosen[::-1]


def outliers(start: LatLon, points: list[LatLon], finish: LatLon | None, min_km: float) -> list[int]:
    """Indices des lieux isolés : homonyme lointain resté seul candidat, erreur de lecture du descriptif.

    Un lieu est isolé si son plus proche voisin (autre lieu, départ ou arrivée) est à plus de `min_km` et à plus
    de 3 fois l'écart habituel entre lieux voisins. Retirés un à un, du plus isolé au moins isolé ; à partir de
    3 lieux seulement (une boucle vers un sommet unique n'est pas suspecte).
    """
    anchors = [start] + ([finish] if finish is not None else [])
    keep = list(range(len(points)))
    removed: list[int] = []
    while len(keep) >= 3:
        pts = [points[i] for i in keep]
        nearest = [min(_km(p, q) for q in anchors + pts[:k] + pts[k + 1 :]) for k, p in enumerate(pts)]
        worst = max(range(len(pts)), key=nearest.__getitem__)
        others = sorted(nearest[:worst] + nearest[worst + 1 :])
        usual = others[len(others) // 2]
        if nearest[worst] <= max(min_km, 3 * usual):
            break
        removed.append(keep.pop(worst))
    return sorted(removed)


def normalize(name: str) -> str:
    """Nom comparable : minuscules, sans accents ni ponctuation (« L’Aubarède » = « l aubarede »)."""
    import unicodedata

    s = unicodedata.normalize("NFKD", name.casefold())
    s = "".join(ch if ch.isalnum() else " " for ch in s if not unicodedata.combining(ch))
    return " ".join(s.split())
