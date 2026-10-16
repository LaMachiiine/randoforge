"""Faune observée autour d'un tracé : occurrences GBIF (agrège iNaturalist, INPN, réseaux naturalistes…), sans clé.

Ce sont des **observations** (où et quand des espèces ont été vues), pas des aires de répartition : une espèce
discrète peut être présente sans observation. Données sous CC0 / CC BY selon les jeux sources ;
citer « GBIF.org » et ses contributeurs.
"""

from __future__ import annotations

import re

from ..http import DAY, CachedHttp

SEARCH = "https://api.gbif.org/v1/occurrence/search"
SPECIES = "https://api.gbif.org/v1/species/{key}"
NAMES = "https://api.gbif.org/v1/species/{key}/vernacularNames"
# Groupes (clés de classe du référentiel GBIF ; serpents et lézards sont classés à part des « reptiles »).
GROUPS = {
    "mammifères": [359],
    "oiseaux": [212],
    "reptiles": [358, 11592253],
    "amphibiens": [131],
}
# Genre Vipera, loup, ours brun, lynx (clés du référentiel GBIF, vérifiées par /species/match).
NOTABLE_KEYS = [2469892, 5219173, 2433433, 2435240]
ATTRIBUTION = "Observations : GBIF.org (iNaturalist, INPN, réseaux naturalistes…), licences CC0 / CC BY des jeux"


class GbifWildlife:
    name = "GBIF"

    def __init__(self, http: CachedHttp):
        self.http = http

    def species_counts(
        self, bbox: tuple[float, float, float, float], months: tuple[int, int], years: tuple[int, int],
        class_keys: list[int], limit: int,
    ) -> tuple[int, list[tuple[int, int]]]:  # fmt: skip
        """(observations totales, [(clé d'espèce, nombre d'observations)…]) dans le rectangle (sud, ouest, nord, est)."""
        s, w, n, e = bbox
        params = [
            ("decimalLatitude", f"{s:.4f},{n:.4f}"), ("decimalLongitude", f"{w:.4f},{e:.4f}"),
            ("month", f"{months[0]},{months[1]}"), ("year", f"{years[0]},{years[1]}"),
            ("occurrenceStatus", "PRESENT"), ("limit", "0"), ("facet", "speciesKey"), ("facetLimit", str(limit)),
        ] + [("classKey", str(k)) for k in class_keys]  # fmt: skip
        url = SEARCH + "?" + "&".join(f"{k}={v}" for k, v in params)
        res = self.http.request_json("GET", url, ttl_s=7 * DAY, service="GBIF")
        counts = (res.get("facets") or [{}])[0].get("counts", []) if res.get("facets") else []
        return int(res.get("count", 0)), [(int(c["name"]), int(c["count"])) for c in counts]

    def notable_counts(
        self, bbox: tuple[float, float, float, float], months: tuple[int, int], years: tuple[int, int]
    ) -> list[tuple[int, int]]:
        """Observations des espèces à connaître (vipères, loup, ours, lynx), quel que soit leur rang."""
        s, w, n, e = bbox
        params = [
            ("decimalLatitude", f"{s:.4f},{n:.4f}"), ("decimalLongitude", f"{w:.4f},{e:.4f}"),
            ("month", f"{months[0]},{months[1]}"), ("year", f"{years[0]},{years[1]}"),
            ("occurrenceStatus", "PRESENT"), ("limit", "0"), ("facet", "speciesKey"), ("facetLimit", "20"),
        ] + [("taxonKey", str(k)) for k in NOTABLE_KEYS]  # fmt: skip
        url = SEARCH + "?" + "&".join(f"{k}={v}" for k, v in params)
        res = self.http.request_json("GET", url, ttl_s=7 * DAY, service="GBIF")
        counts = (res.get("facets") or [{}])[0].get("counts", []) if res.get("facets") else []
        return [(int(c["name"]), int(c["count"])) for c in counts]

    def names(self, key: int) -> tuple[str, str | None]:
        """(nom scientifique, nom français usuel ou None)."""
        sp = self.http.request_json("GET", SPECIES.format(key=key), ttl_s=90 * DAY, service="GBIF")
        vern = self.http.request_json("GET", NAMES.format(key=key), params={"limit": 200}, ttl_s=90 * DAY,
                                      service="GBIF")  # fmt: skip
        fr = [(v["vernacularName"].strip(), v.get("source") or "") for v in vern.get("results", [])
              if v.get("language") == "fra"]  # fmt: skip
        # Référentiel national TAXREF d'abord (« Renard roux, Renard, Goupil » → « Renard roux »), puis EUNIS ;
        # sinon la forme la plus simple (les autres listes contiennent des noms anciens : « Goupil », « Palombe »).
        name = None
        for ref in ("TAXREF", "EUNIS"):
            if found := [n for n, src in fr if ref in src]:
                name = found[0].split(",")[0].strip()
                break
        if name is None and fr:
            simple = sorted((n for n, _ in fr if "," not in n), key=len)
            name = simple[0] if simple else fr[0][0]
        if name:
            name = re.sub(r"\s*\((?:La|Le|Les|L')\)\s*$", "", name)  # « Vipère aspic (La) » → « Vipère aspic »
        return sp.get("canonicalName") or sp.get("scientificName") or str(key), (
            name[:1].upper() + name[1:]
        ) if name else None
