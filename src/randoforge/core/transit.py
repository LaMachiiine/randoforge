"""Passages de transport en commun regroupés par ligne et direction (calcul pur sur les réponses Transitous)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from .geo import distance_m

NOT_TRANSIT = ("covoit",)  # lignes de covoiturage présentées comme des bus : écartées


@dataclass
class Line:
    ligne: str
    direction: str
    horaires: list[str] = field(default_factory=list)  # heures locales « HH:MM »


@dataclass
class Stops:
    arrets: list[tuple[str, float]]  # (nom, distance en m), du plus proche au plus loin
    lignes: list[Line]
    premier_apres: tuple[str, str, str] | None = None  # (heure, ligne, direction) après l'heure donnée


def _dedupe(times: list[str], within_min: int = 2) -> list[str]:
    """Un même car vu à deux arrêts voisins (« 06:50 », « 06:51 ») : un seul passage."""
    out: list[str] = []
    for t in times:
        m = int(t[:2]) * 60 + int(t[3:])
        if not out or m - (int(out[-1][:2]) * 60 + int(out[-1][3:])) > within_min:
            out.append(t)
    return out


def _local(iso: str, tz: ZoneInfo) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz)


def group(stop_times: list[dict], lat: float, lon: float, tz: ZoneInfo, day, after: datetime | None = None) -> Stops:
    """Passages du jour `day` regroupés par (ligne, direction), sans covoiturage ni simples arrivées au terminus ;
    `after` (heure locale) : premier passage ensuite, pour le retour."""
    lines: dict[tuple[str, str], Line] = {}
    stops: dict[str, float] = {}
    first: tuple[datetime, str, str] | None = None
    for st in stop_times:
        place = st.get("place", {})
        agency = (st.get("agencyName") or "").lower()
        if any(w in agency for w in NOT_TRANSIT) or place.get("pickupType", "NORMAL") != "NORMAL":
            continue
        if place.get("stopId") and place.get("stopId") == (st.get("tripTo") or {}).get("stopId"):
            continue  # terminus : le véhicule arrive, il ne repart pas
        when_iso = place.get("departure") or place.get("arrival")
        if not when_iso:
            continue
        when = _local(when_iso, tz)
        if when.date() != day:
            continue
        name = (place.get("name") or "").split(",")[-1].strip() or "arrêt"
        stops[name] = min(stops.get(name, 1e9), distance_m((lat, lon), (place["lat"], place["lon"])))
        code = st.get("routeShortName") or st.get("routeLongName") or (st.get("mode") or "").lower()
        direction = (st.get("headsign") or (st.get("tripTo") or {}).get("name") or "?").split(",")[-1].strip()
        line = lines.setdefault((code, direction), Line(code, direction))
        hhmm = when.strftime("%H:%M")
        if hhmm not in line.horaires:
            line.horaires.append(hhmm)
        if after and when >= after and (first is None or when < first[0]):
            first = (when, code, direction)
    ordered = sorted(lines.values(), key=lambda li: (li.ligne, li.direction))
    for li in ordered:
        li.horaires = _dedupe(sorted(li.horaires))
    return Stops(
        arrets=sorted(((n, round(d)) for n, d in stops.items()), key=lambda x: x[1]),
        lignes=ordered,
        premier_apres=(first[0].strftime("%H:%M"), first[1], first[2]) if first else None,
    )
