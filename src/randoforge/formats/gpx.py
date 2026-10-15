"""Lecture et écriture GPX."""

from __future__ import annotations

import gpxpy
import gpxpy.gpx

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


def write_gpx(route: Route) -> str:
    gpx = gpxpy.gpx.GPX()
    gpx.name = route.name
    gpx.description = ATTRIBUTION
    gpx.creator = "RandoForge"
    track = gpxpy.gpx.GPXTrack(name=route.name)
    segment = gpxpy.gpx.GPXTrackSegment()
    segment.points.extend(gpxpy.gpx.GPXTrackPoint(p.lat, p.lon, elevation=p.ele) for p in route.points)
    track.segments.append(segment)
    gpx.tracks.append(track)
    for p in route.pois or []:
        if p.nom or p.score >= 0.3 or p.via:
            label = p.nom or POI_LABELS.get(p.categorie, p.categorie)
            if p.via:
                label = f"{label} ({p.via})"
            gpx.waypoints.append(
                gpxpy.gpx.GPXWaypoint(
                    p.lat, p.lon, elevation=p.ele, name=label, type=p.categorie, comment=f"km {p.km:.1f}"
                )
            )
    return gpx.to_xml()
