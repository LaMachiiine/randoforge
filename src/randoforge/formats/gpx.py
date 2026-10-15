"""Lecture et écriture GPX."""

from __future__ import annotations

import gpxpy
import gpxpy.gpx
import numpy as np

from ..core.geo import cumulative_distance
from ..core.models import Route, TrackPoint

POI_LABELS = {
    "cascade": "Cascade",
    "point_de_vue": "Point de vue",
    "lac": "Lac",
    "sommet": "Sommet",
    "curiosite": "Curiosité",
    "riviere": "Cours d'eau",
    "patrimoine": "Patrimoine",
    "eau": "Point d'eau",
    "pause": "Abri / pause",
}

ATTRIBUTION = "Généré par RandoForge. Données © contributeurs OpenStreetMap (ODbL)."


def read_gpx(text: str) -> tuple[str | None, list[TrackPoint]]:
    """Renvoie (nom, points). Concatène les traces ; à défaut, les routes GPX."""
    gpx = gpxpy.parse(text)
    points = [
        TrackPoint(lat=p.latitude, lon=p.longitude, ele=p.elevation)
        for track in gpx.tracks
        for segment in track.segments
        for p in segment.points
    ]
    if not points:
        points = [
            TrackPoint(lat=p.latitude, lon=p.longitude, ele=p.elevation) for route in gpx.routes for p in route.points
        ]
    name = gpx.name or next((t.name for t in gpx.tracks if t.name), None)
    return name, points


def write_gpx(route: Route, day: int | None = None) -> str:
    """GPX de l'itinéraire complet (une seule trace), ou d'une seule étape si `day` est donné.

    Les waypoints (nuits, points notables) sont limités à la portion exportée.
    """
    cum = cumulative_distance(np.array([p.lat for p in route.points]), np.array([p.lon for p in route.points]))
    start, end, name = 0.0, float("inf"), route.name
    if day is not None:
        stage = next((s for s in route.stages or [] if s.jour == day), None)
        if stage is None:
            raise ValueError(f"Pas d'étape n°{day} : lancer plan_stages d'abord.")
        start, end = stage.km_debut * 1000, stage.km_fin * 1000
        name = f"{route.name} — jour {day} ({stage.distance_km:.1f} km, {stage.d_plus_m} m D+)"

    gpx = gpxpy.gpx.GPX()
    gpx.name = name
    gpx.description = ATTRIBUTION
    gpx.creator = "RandoForge"
    track = gpxpy.gpx.GPXTrack(name=name)
    segment = gpxpy.gpx.GPXTrackSegment()
    segment.points.extend(
        gpxpy.gpx.GPXTrackPoint(p.lat, p.lon, elevation=p.ele)
        for p, m in zip(route.points, cum, strict=True)
        if start - 1 <= m <= end + 1
    )
    track.segments.append(segment)
    gpx.tracks.append(track)

    def within(km: float) -> bool:
        return start - 1 <= km * 1000 <= end + 1

    for s in (route.stages or [])[:-1]:
        if within(s.km_fin):
            i = int(np.searchsorted(cum, s.km_fin * 1000))
            p = route.points[min(i, len(route.points) - 1)]
            gpx.waypoints.append(
                gpxpy.gpx.GPXWaypoint(
                    p.lat,
                    p.lon,
                    elevation=p.ele,
                    name=f"Nuit {s.jour} : {s.arrivee}",
                    type="hebergement",
                    comment=f"km {s.km_fin:.1f}",
                )
            )
    for p in route.pois or []:
        if (p.nom or p.score >= 0.3 or p.via) and within(p.km):
            label = p.nom or POI_LABELS.get(p.categorie, p.categorie)
            if p.via:
                label = f"{label} ({p.via})"
            gpx.waypoints.append(
                gpxpy.gpx.GPXWaypoint(
                    p.lat, p.lon, elevation=p.ele, name=label, type=p.categorie, comment=f"km {p.km:.1f}"
                )
            )
    return gpx.to_xml()
