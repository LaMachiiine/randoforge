from randoforge.core.models import Poi, Route, TechnicalPassage, TrackPoint
from randoforge.formats.html import write_map
from randoforge.formats.markdown import write_fiche

EVIL = "</script><script>alert(1)</script>"


def _route(**kw):
    return Route(
        route_id="r_2026-10-15_aaaaaa",
        name="<b>Test</b>",
        source="test",
        points=[TrackPoint(lat=45, lon=6, ele=1000), TrackPoint(lat=45.01, lon=6, ele=1100)],
        **kw,
    )


def test_map_neutralises_osm_names():
    # Les noms OSM sont modifiables par n'importe qui : ils ne doivent pas pouvoir injecter de script.
    poi = Poi(
        km=0.5,
        categorie="cascade",
        type="waterfall",
        nom=EVIL,
        lat=45.005,
        lon=6,
        distance_m=0,
        detour_m=0,
        score=0.9,
        osm_id="node/1",
    )
    page = write_map(_route(pois=[poi]))
    # Seul « </script » peut fermer le bloc de données : il ne doit apparaître que pour les 2 vrais blocs.
    assert page.count("</script") == 2
    assert EVIL not in page
    assert "&lt;b&gt;Test&lt;/b&gt;" in page


def test_map_and_fiche_show_technical_passages():
    tech = TechnicalPassage(
        km=0.2,
        longueur_m=150,
        niveau="T3",
        types=["pente forte"],
        details=["Pente jusqu'à 45 % sur ~150 m"],
        sources=["MNT"],
    )
    route = _route(technical=[tech])
    page = write_map(route)
    assert 'class="tech"' in page
    # Un sélecteur CSS « svg » global écraserait le SVG du tracé Leaflet (tracé invisible) : régression vue en vrai.
    assert " svg {" not in page.replace(".profile svg {", "")
    fiche = write_fiche(route)
    assert "## Passages techniques" in fiche and "niveau_technique: T3" in fiche
