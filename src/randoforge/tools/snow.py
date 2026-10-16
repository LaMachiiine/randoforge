"""Outil MCP : conditions d'enneigement le long d'un itinéraire."""

from __future__ import annotations

from datetime import date as Date
from datetime import timedelta

import numpy as np
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ..app import App
from ..core import snow as snow_lib
from ..core.geo import cumulative_distance
from ..core.models import SnowReport
from ..core.timing import format_duration
from ..engines.snow import SCL_CLOUDS, SCL_NODATA, SCL_SNOW

SAMPLE_M = 250  # un état de neige tous les 250 m le long du tracé
MODEL_POINTS = 25  # points envoyés au modèle (un appel)
MARGIN_DEG = 0.05  # secteur observé autour du tracé (~5 km) pour la limite de la neige
SAT_DAYS_BACK = 4  # vues satellite des 4 jours précédents si nuages
FORECAST_DAYS = 15


def register(mcp: MCPServer, app: App) -> None:
    @mcp.tool()
    def snow_conditions(
        route_id: str, date: Date | None = None, en_raquettes: bool = False, force: bool = False
    ) -> SnowReport:
        """Enneigement le long du tracé et durée ajustée, en saison froide (oct.–juin) au-dessus de 600 m ou toute
        l'année au-dessus de 2 000 m (`force=True` pour analyser quand même).

        - **Satellites** (observation réelle, sans nuage) : MODIS/VIIRS quotidiens à 500 m, affinés par
          Sentinel-2 à 20 m si une image récente existe ; **limite de la neige** = croisement avec le relief.
        - **Modèle** Open-Meteo : épaisseur et neige fraîche (estimation, les modèles divergent en relief) ;
          seule source pour une date future.
        - **Durée ajustée** par tronçon enneigé (facteurs documentés, ×1,25 à ×3) : une estimation, à annoncer « ≈ ».
        `date` : jour de la sortie (défaut : set_constraints, sinon aujourd'hui). `en_raquettes` : facteurs raquettes.
        """
        route = app.load(route_id)
        s = route.stats
        if s is None or s.alt_max_m is None:
            raise ToolError("Altitudes manquantes : impossible de juger l'enneigement.")
        today = Date.today()
        day = date or route.request.date or today
        lats = np.array([p.lat for p in route.points])
        lons = np.array([p.lon for p in route.points])
        if not force and not snow_lib.in_season(day, float(lats.mean()), s.alt_max_m):
            report = SnowReport(applicable=False, date=day, message=(
                f"Hors saison froide ou altitude basse (point culminant {s.alt_max_m} m) : enneigement non analysé."))  # fmt: skip
            route.snow = report
            app.save(route)
            return report

        observed_day = min(day, today)  # les satellites ne voient pas l'avenir
        bbox = (float(lats.min()) - MARGIN_DEG, float(lons.min()) - MARGIN_DEG,
                float(lats.max()) + MARGIN_DEG, float(lons.max()) + MARGIN_DEG)  # fmt: skip
        cum = cumulative_distance(lats, lons)
        idx = list(np.unique(np.searchsorted(cum, np.arange(0, cum[-1], SAMPLE_M))))
        samples = [(route.points[i].lat, route.points[i].lon) for i in idx]
        step = max(1, len(idx) // MODEL_POINTS)
        model_idx = idx[::step]
        model_pts = [(route.points[i].lat, route.points[i].lon, route.points[i].ele) for i in model_idx]
        services = app.services
        calls = {}
        if services.snow_sat:
            calls["sat"] = lambda: app.external(lambda: services.snow_sat.composite(bbox, observed_day, SAT_DAYS_BACK))
        if services.snow_s2:
            calls["s2"] = lambda: app.external(lambda: _sentinel2(services.snow_s2, bbox, observed_day, samples))
        if services.snow_model and day <= today + timedelta(days=FORECAST_DAYS):
            calls["model"] = lambda: app.external(lambda: services.snow_model.snow(model_pts, day))
        res = app.parallel(calls)
        warnings: list[str] = []
        sources: list[str] = []
        for name, label in (("sat", "satellites"), ("s2", "Sentinel-2"), ("model", "modèle Open-Meteo")):
            if isinstance(res.get(name), ToolError):
                warnings.append(f"Source indisponible ({label}) : {res[name]}")
                res[name] = None

        # 1. Satellites quotidiens : état par point et limite de la neige (croisement avec le relief).
        grid = res.get("sat")
        line = None
        seen: list[bool | None] = [None] * len(idx)
        seen_days: list[Date | None] = [None] * len(idx)
        limite_source = None
        if grid is not None:
            sources.append(f"{', '.join(sorted(grid.sources)) or 'MODIS / VIIRS'} (NASA GIBS, 500 m)")
            for k, (la, lo) in enumerate(samples):
                rc = grid.index(la, lo)
                if rc and grid.values[rc] >= 0:
                    seen[k] = bool(grid.values[rc] >= snow_lib.PARTIAL_NDSI)
                    seen_days[k] = Date.fromordinal(int(grid.days[rc]))
            plats, plons = grid.centers()
            mesh_lat, mesh_lon = np.meshgrid(plats, plons, indexing="ij")
            clear = grid.values >= 0
            if clear.sum() >= snow_lib.MIN_BAND_PX:
                pts = list(zip(mesh_lat[clear].tolist(), mesh_lon[clear].tolist(), strict=True))
                try:
                    elev = np.array([np.nan if v is None else v for v in app.elevations(pts).values], dtype=float)
                    ok = ~np.isnan(elev)
                    line, lo_e, hi_e = snow_lib.snow_line(elev[ok], grid.values[clear][ok])
                    days_seen = sorted({Date.fromordinal(int(d)) for d in grid.days[clear] if d})
                    when = days_seen[-1].strftime("%d/%m") if days_seen else "?"
                    visible = round(100 * clear.mean())
                    if line is not None:
                        limite_source = f"satellites, vue du {when} ({visible} % du secteur visible)"
                    elif hi_e == hi_e:  # pas NaN
                        limite_source = f"aucune neige vue jusqu'à {hi_e:.0f} m (satellites, {when})"
                except ToolError as exc:
                    warnings.append(f"Altitudes du secteur indisponibles : limite de la neige non calculée ({exc})")

        # 2. Sentinel-2 (20 m) : remplace l'état des points qu'il voit sans nuage.
        s2_label = None
        if (s2 := res.get("s2")) and s2[0]:
            s2_day, classes = s2
            n_seen = 0
            for k, c in enumerate(classes):
                if c is None or c in SCL_CLOUDS | SCL_NODATA:
                    continue  # nuage ou ombre : l'état satellite quotidien (ou l'estimation) reste
                seen[k] = c in SCL_SNOW
                seen_days[k] = Date.fromisoformat(s2_day)
                n_seen += 1
            if n_seen:
                s2_label = (
                    f"image du {Date.fromisoformat(s2_day):%d/%m} ({round(100 * n_seen / len(classes))} % du tracé vu)"
                )
                sources.append("Sentinel-2 (20 m, Copernicus)")

        # 3. Modèle : épaisseur et neige fraîche, affectées au point modèle le plus proche.
        model = res.get("model") or []
        depths = [m["snow_depth_m"] for m in model if m.get("snow_depth_m") is not None]
        falls = [m["snowfall_72h_cm"] for m in model if m.get("snowfall_72h_cm") is not None]
        if model:
            sources.append("modèle Open-Meteo (épaisseur, neige fraîche : estimation)")
        states = []
        for k, i in enumerate(idx):
            m = model[min(len(model) - 1, k // step)] if model else {}
            depth = m.get("snow_depth_m")
            states.append((i, snow_lib.PointSnow(
                seen=seen[k], seen_day=seen_days[k], depth_cm=None if depth is None else depth * 100,
                fresh=(m.get("snowfall_72h_cm") or 0) >= snow_lib.FRESH_CM)))  # fmt: skip
        if not sources:
            raise ToolError("Aucune source d'enneigement disponible : " + " ; ".join(warnings))

        normal, with_snow, snow_km, sections = snow_lib.duration_with_snow(
            route.points, cum, states, line, s.profile, en_raquettes
        )
        km_total = cum[-1] / 1000
        seen_pct = round(100 * sum(v is not None for v in seen) / len(seen)) if seen else 0
        snow_pct = round(100 * snow_km / km_total) if km_total else 0
        ratio = with_snow / normal if normal else 1.0
        duree_neige = round((s.duration_min or 0) * ratio) if s.duration_min else None
        if day > today:
            warnings.append(f"Sortie dans {(day - today).days} j : satellites = état d'aujourd'hui ; d'ici là seul le "
                            "modèle prévoit l'évolution.")  # fmt: skip
        if 0 < seen_pct < 60:
            warnings.append(f"Tracé vu sans nuage sur {seen_pct} % seulement : le reste est estimé (limite ou modèle).")
        if depths and max(depths) * 100 >= 2 and line is None and grid is not None and not any(seen):
            warnings.append("Le modèle annonce de la neige que les satellites ne voient pas : à vérifier.")
        if snow_pct == 0:
            message = "Pas de neige probable sur le tracé."
        else:
            message = f"Neige probable sur {snow_pct} % du tracé ({snow_km:.1f} km)"
            if line is not None:
                message += f", au-dessus de ~{line:.0f} m"
            message += "."
        report = SnowReport(
            applicable=True, message=message, date=day,
            limite_neige_m=None if line is None else int(line), limite_source=limite_source,
            part_enneigee_pct=snow_pct,
            troncons_enneiges=[f"km {a:.1f}–{b:.1f} (×{f:g})" for a, b, f in sections],
            vu_par_satellite_pct=seen_pct if grid is not None or s2_label else None, sentinel2=s2_label,
            epaisseur_modele_cm=(round(min(depths) * 100), round(max(depths) * 100)) if depths else None,
            neige_fraiche_72h_cm=max(falls) if falls else None, en_raquettes=en_raquettes,
            duree_normale=s.duration_label,
            duree_neige=format_duration(duree_neige) if duree_neige and snow_pct else s.duration_label,
            sources=sources, avertissements=warnings,
        )  # fmt: skip
        route.snow = report
        app.save(route)
        return report


def _sentinel2(s2, bbox, day: Date, samples: list[tuple[float, float]]):
    items = s2.scene(bbox, day)
    if not items:
        return None, []
    return s2.classes(items, samples)
