"""Zones réglementées traversées : parcs nationaux, réserves, zones protégées, terrains militaires.

RandoForge n'affirme jamais qu'une activité est « autorisée » : il signale les zones et les
restrictions connues ou probables, et renvoie vers le gestionnaire du site.
"""

from __future__ import annotations

from .models import AreaCrossing, TrackPoint
from .osmgeom import RouteFrame, element_geometry

MERGE_GAP_KM = 0.3
RESTRICTIVE_CLASSES = {"1", "1a", "1b", "2", "3", "4"}  # UICN : réserves intégrales → aires de gestion
SOFT_CLASSES = {"5", "6"}  # paysages protégés (ex. parcs naturels régionaux), usage durable


def build_query(points: list[TrackPoint]) -> str:
    bbox = RouteFrame(points).bbox(50)
    return (
        "[out:json][timeout:120];("
        f'nwr["boundary"~"^(national_park|protected_area)$"]({bbox});'
        f'nwr["leisure"="nature_reserve"]({bbox});'
        f'nwr["landuse"="military"]({bbox});'
        f'nwr["military"~"^(danger_area|range|training_area)$"]({bbox});'
        ");out geom;"
    )


def _dog_rule(tags: dict, default: str | None) -> str | None:
    dog = tags.get("dog")
    if dog in {"no"}:
        return "interdits"
    if dog in {"leashed", "leash"}:
        return "en laisse"
    if dog in {"yes"}:
        return "autorisés"
    return default


def classify(tags: dict) -> tuple[str, str | None, str | None, list[str]] | None:
    """(type, chiens, bivouac, notes) ou None si la zone n'impose rien de notable."""
    pc = tags.get("protect_class")
    camping = tags.get("camping") or tags.get("tents")
    biv = "interdit" if camping == "no" else None
    if tags.get("landuse") == "military" or "military" in tags:
        if tags.get("access") in {"yes", "permissive"}:
            return (
                "zone militaire (accès autorisé)",
                None,
                None,
                ["Respecter le balisage et les éventuels tirs annoncés."],
            )
        return "zone militaire", None, "interdit", ["Accès interdit ou réglementé (tirs, manœuvres)."]
    if tags.get("boundary") == "national_park" or pc == "2":
        notes = [
            "Réglementation de parc national : chiens généralement interdits (même tenus en laisse), "
            "bivouac encadré (horaires, distance aux refuges), feux et cueillette interdits.",
            "Vérifier le règlement du parc avant de partir.",
        ]
        return "parc national", _dog_rule(tags, "interdits"), biv or "réglementé", notes
    if tags.get("leisure") == "nature_reserve" or pc in RESTRICTIVE_CLASSES:
        notes = [
            "Réserve / zone protégée stricte : chiens et bivouac souvent interdits, rester sur les sentiers.",
            "Vérifier la réglementation locale (panneaux, gestionnaire).",
        ]
        kind = "réserve naturelle" if tags.get("leisure") == "nature_reserve" else "zone protégée stricte"
        return kind, _dog_rule(tags, None), biv or "réglementé", notes
    if pc in SOFT_CLASSES:
        return (
            "parc naturel régional / paysage protégé",
            _dog_rule(tags, None),
            biv,
            ["Pas de restriction générale connue : respecter la réglementation locale."],
        )
    if biv or tags.get("dog"):
        return "zone protégée", _dog_rule(tags, None), biv, []
    return None


def crossings(points: list[TrackPoint], elements: list[dict]) -> list[AreaCrossing]:
    frame = RouteFrame(points)
    out: list[AreaCrossing] = []
    seen: set[tuple] = set()
    for el in elements:
        tags = el.get("tags", {})
        found = classify(tags)
        if not found:
            continue
        geom = element_geometry(el, frame.proj)
        if geom is None or geom.geom_type not in {"Polygon", "MultiPolygon"}:
            continue
        kind, dogs, biv, notes = found
        if tags.get("protection_title") and "militaire" not in kind:
            kind = tags["protection_title"].lower()  # libellé officiel (ex. « réserve biologique intégrale »)
        for start, end in frame.ranges_on(geom):
            key = (tags.get("name"), kind, round(start, -2))
            if key in seen:
                continue  # même zone cartographiée deux fois (way + relation)
            seen.add(key)
            # Fragments d'une même zone : même nom et type, et portions qui se touchent (à MERGE_GAP_KM près).
            prev = next(
                (a for a in out if a.nom == tags.get("name") and a.kind == kind
                 and start / 1000 - MERGE_GAP_KM < a.km_fin and a.km_debut < end / 1000 + MERGE_GAP_KM),
                None,
            )  # fmt: skip
            if prev:
                prev.km_debut = round(min(prev.km_debut * 1000, start) / 1000, 2)
                prev.km_fin = round(max(prev.km_fin * 1000, end) / 1000, 2)
                continue
            out.append(
                AreaCrossing(
                    nom=tags.get("name"),
                    kind=kind,
                    protect_class=tags.get("protect_class"),
                    km_debut=round(start / 1000, 2),
                    km_fin=round(end / 1000, 2),
                    chiens=dogs,
                    bivouac=biv,
                    notes=notes,
                    osm_id=f"{el['type']}/{el['id']}",
                )
            )
    return sorted(out, key=lambda a: a.km_debut)


def area_at(areas: list[AreaCrossing], km: float) -> list[AreaCrossing]:
    return [a for a in areas if a.km_debut - 0.05 <= km <= a.km_fin + 0.05]
