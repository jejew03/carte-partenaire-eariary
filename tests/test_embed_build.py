"""
Tests de la lecture du Sheet utilisée par l'iframe (`static/embed/build.py`).

Aucun accès réseau : les CSV sont écrits à la main. Ces règles sont dupliquées
en JavaScript dans `static/embed/assets/data.js` pour la relecture en direct — toute
correction ici doit y être reportée.
"""

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "static" / "embed"))

import build as embed_build  # noqa: E402


ENTETE = "Province,Nom de l'établissement,Catégorie,Latitude / longitude\n"


def lire(csv):
    return embed_build.parse_rows(csv)


# --------------------------------------------------------------------------- #
# Lecture nominale
# --------------------------------------------------------------------------- #


def test_ligne_complete():
    (etab,) = lire(ENTETE + 'Toamasina,Chez X,Restaurant,"-18.15, 49.41"\n')
    assert etab == {
        "nom": "Chez X",
        "categorie": "Restaurant",
        "province": "Toamasina",
        "lat": -18.15,
        "lon": 49.41,
        "coordonnees_brutes": "-18.15, 49.41",
    }


def test_entete_precedee_de_lignes_de_titre():
    """La vraie ligne d'en-tête est celle qui contient « Province »."""
    csv = "Carte des partenaires,,,\n,,,\n" + ENTETE + 'Sambava,Magasin Y,Magasin,"-14.25, 50.15"\n'
    (etab,) = lire(csv)
    assert etab["nom"] == "Magasin Y"


def test_colonnes_dans_un_autre_ordre():
    """Les colonnes sont retrouvées par mots-clés, pas par position."""
    csv = (
        "Nom de l'établissement,Latitude / longitude,Province,Catégorie\n"
        'Chez Z,"-21.44, 47.08",Fianarantsoa,Restaurant\n'
    )
    (etab,) = lire(csv)
    assert (etab["nom"], etab["province"], etab["lat"]) == ("Chez Z", "Fianarantsoa", -21.44)


def test_nom_avec_virgules_et_guillemets():
    csv = ENTETE + 'Mahajanga,"Store (« épices, saveurs »)",Épicerie,"-15.72, 46.31"\n'
    (etab,) = lire(csv)
    assert etab["nom"] == "Store (« épices, saveurs »)"


# --------------------------------------------------------------------------- #
# Nettoyage
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "brut, attendu",
    [
        ("Supermaché", "Supermarché"),
        ("Supermarche", "Supermarché"),
        ("Epicerie ", "Épicerie"),
        ("HOTEL", "Hôtel"),
        ("restaurant", "Restaurant"),
        ("", "Non renseignée"),
    ],
)
def test_categories_harmonisees(brut, attendu):
    (etab,) = lire(ENTETE + f'Toamasina,Chez X,{brut},"-18.15, 49.41"\n')
    assert etab["categorie"] == attendu


@pytest.mark.parametrize(
    "brut, attendu",
    [
        ("Antsirananana", "Antsiranana"),
        ("Fianaratsoa", "Fianarantsoa"),
        ("Sambava", "Sambava"),
    ],
)
def test_provinces_corrigees(brut, attendu):
    """Fautes de frappe du Sheet, corrigées parce que l'iframe est publique."""
    (etab,) = lire(ENTETE + f'{brut},Chez X,Restaurant,"-18.15, 49.41"\n')
    assert etab["province"] == attendu


# --------------------------------------------------------------------------- #
# Coordonnées
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "brut",
    [
        "Introuvable, quartier Amparihy",
        "",
        "à venir",
        "-18.15",
        "200.0, 49.41",  # latitude hors bornes
    ],
)
def test_coordonnees_illisibles_gardent_l_etablissement(brut):
    """Sans point exploitable, la fiche reste dans la liste — sans marqueur."""
    (etab,) = lire(ENTETE + f'Toamasina,Chez X,Restaurant,"{brut}"\n')
    assert etab["lat"] is None and etab["lon"] is None
    assert etab["coordonnees_brutes"] == brut


@pytest.mark.parametrize(
    "brut, lat, lon",
    [
        ("-18.15, 49.41", -18.15, 49.41),
        ("-18.15 ; 49.41", -18.15, 49.41),
        ("\\-18.15, \\49.41", -18.15, 49.41),  # antislashs collés par le Sheet
        ("-18,15, 49,41", -18.15, 49.41),  # virgule décimale
    ],
)
def test_variantes_de_coordonnees(brut, lat, lon):
    assert embed_build.parse_coords(brut) == (lat, lon)


# --------------------------------------------------------------------------- #
# Lignes ignorées
# --------------------------------------------------------------------------- #


def test_lignes_sans_nom_ignorees():
    csv = ENTETE + ',,,\nToamasina,,Restaurant,"-18.15, 49.41"\nToamasina,nan,Restaurant,"-18.15, 49.41"\n'
    assert lire(csv) == []


def test_feuille_vide():
    with pytest.raises(ValueError):
        lire("")


# --------------------------------------------------------------------------- #
# Région administrative
# --------------------------------------------------------------------------- #
# Le Sheet ne porte pas la région : elle est déduite des coordonnées, par
# appartenance au polygone ADM1. Les cas généraux se testent sur des carrés
# écrits à la main ; les vraies limites servent au test d'intégration final.


def _geojson(chemin, entites):
    chemin.write_text(
        json.dumps({"type": "FeatureCollection", "features": entites}),
        encoding="utf-8",
    )
    return chemin


def _carre(nom, lon, lat, cote=1.0, trous=()):
    """Entité GeoJSON carrée, coin inférieur gauche en (lon, lat)."""
    anneau = [
        [lon, lat],
        [lon + cote, lat],
        [lon + cote, lat + cote],
        [lon, lat + cote],
        [lon, lat],
    ]
    return {
        "type": "Feature",
        "properties": {"nom_zone": nom},
        "geometry": {"type": "Polygon", "coordinates": [anneau] + [list(t) for t in trous]},
    }


@pytest.fixture
def deux_carres(tmp_path):
    """Deux régions jointives : Est sur [46,47], Ouest sur [45,46]."""
    return embed_build.charger_regions(
        _geojson(tmp_path / "adm1.geojson", [_carre("Est", 46, -19), _carre("Ouest", 45, -19)])
    )


def test_point_dans_le_polygone(deux_carres):
    assert embed_build.region_de(-18.5, 46.5, deux_carres) == "Est"
    assert embed_build.region_de(-18.5, 45.5, deux_carres) == "Ouest"


def test_sans_coordonnees_pas_de_region(deux_carres):
    assert embed_build.region_de(None, None, deux_carres) == ""
    assert embed_build.region_de(-18.5, None, deux_carres) == ""


def test_sans_limites_pas_de_region():
    """L'absence de `data/geo/` n'est pas une erreur : l'instantané s'en passe."""
    assert embed_build.charger_regions(Path("/introuvable/adm1.geojson")) == []
    assert embed_build.region_de(-18.5, 46.5, []) == ""


def test_point_juste_hors_du_polygone_est_rattache(deux_carres):
    """Trait de côte simplifié, GPS approximatif : on rattache au plus proche."""
    assert embed_build.region_de(-18.5, 47.05, deux_carres) == "Est"


def test_point_trop_loin_reste_sans_region(deux_carres):
    """Au-delà de la tolérance, la coordonnée est trop douteuse pour trancher."""
    assert embed_build.region_de(-18.5, 49.0, deux_carres) == ""


def test_multipolygone_et_trou(tmp_path):
    ile = {
        "type": "Feature",
        "properties": {"nom_zone": "Archipel"},
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [
                _carre("", 46, -19)["geometry"]["coordinates"],
                _carre("", 50, -13)["geometry"]["coordinates"],
            ],
        },
    }
    lagon = [[[40, -19], [43, -19], [43, -16], [40, -16], [40, -19]],
             [[41, -18], [42, -18], [42, -17], [41, -17], [41, -18]]]
    atoll = {
        "type": "Feature",
        "properties": {"nom_zone": "Atoll"},
        "geometry": {"type": "Polygon", "coordinates": lagon},
    }
    regions = embed_build.charger_regions(_geojson(tmp_path / "adm1.geojson", [ile, atoll]))

    assert embed_build.region_de(-18.5, 46.5, regions) == "Archipel"
    assert embed_build.region_de(-12.5, 50.5, regions) == "Archipel"  # second polygone
    assert embed_build.region_de(-18.5, 40.5, regions) == "Atoll"
    # Le trou est bien exclu : au centre, la terre est trop loin pour trancher…
    assert embed_build.region_de(-17.5, 41.5, regions) == ""
    # … mais un point tout contre sa rive rejoint la région qui l'entoure.
    assert embed_build.region_de(-17.02, 41.5, regions) == "Atoll"


def test_table_ville_region_et_completion(deux_carres):
    etablissements = [
        {"nom": "A", "province": "Tolagnaro", "lat": -18.5, "lon": 46.5},
        {"nom": "B", "province": "Tolagnaro", "lat": -18.6, "lon": 46.6},
        {"nom": "C", "province": "Tolagnaro", "lat": None, "lon": None},
        {"nom": "D", "province": "Inconnue", "lat": None, "lon": None},
    ]
    assert embed_build.ajouter_regions(etablissements, deux_carres) == 2

    table = embed_build.regions_par_ville(etablissements)
    assert table == {"Tolagnaro": "Est"}

    # La fiche sans coordonnée exploitable hérite de la région de sa ville ;
    # celle dont la ville est inconnue reste sans région.
    assert embed_build.completer_par_ville(etablissements, table) == 1
    assert [e["region"] for e in etablissements] == ["Est", "Est", "Est", ""]


def test_limites_du_depot_situent_les_villes_du_sheet():
    """Test d'intégration : vraies limites ADM1, vraies coordonnées du Sheet."""
    regions = embed_build.charger_regions()
    if not regions:
        pytest.skip("data/geo/mdg_adm1.geojson absent")

    attendu = {
        (-25.025445, 46.990566): "Anosy",  # Tolagnaro
        (-15.718495, 46.304429): "Boeny",  # Mahajanga
        (-14.254504, 50.157256): "Sava",  # Sambava
        (-12.289942, 49.291381): "Diana",  # Antsiranana
        (-21.448425, 47.086873): "Haute Matsiatra",  # Fianarantsoa
        (-18.158589, 49.412152): "Atsinanana",  # Toamasina
    }
    for (lat, lon), region in attendu.items():
        assert embed_build.region_de(lat, lon, regions) == region


# --------------------------------------------------------------------------- #
# Instantané
# --------------------------------------------------------------------------- #


def test_instantane_est_du_javascript_lisible():
    """Le fichier généré doit rester une simple affectation de variable."""
    rendu = embed_build.render(lire(ENTETE + 'Toamasina,Chez X,Restaurant,"-18.15, 49.41"\n'), "2026-01-01T00:00:00Z")
    assert rendu.startswith("/*")
    assert "window.EARIARY_SNAPSHOT = {" in rendu
    assert rendu.rstrip().endswith("};")
    assert "Chez X" in rendu  # accents et guillemets non échappés en \uXXXX


def test_instantane_porte_la_table_ville_region():
    """La page tableau s'en sert pour les lignes relues en direct du Sheet."""
    rendu = embed_build.render([], "2026-01-01T00:00:00Z", {"Tolagnaro": "Anosy"})
    assert '"regions_par_ville"' in rendu
    assert '"Tolagnaro": "Anosy"' in rendu


def test_instantane_du_depot_est_coherent():
    """L'instantané versionné doit être lisible et non vide."""
    fichier = RACINE / "static" / "embed" / "assets" / "etablissements.js"
    contenu = fichier.read_text(encoding="utf-8")
    assert "window.EARIARY_SNAPSHOT" in contenu
    assert '"etablissements"' in contenu
