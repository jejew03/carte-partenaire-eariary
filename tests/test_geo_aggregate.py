"""
Tests du moteur d'agrégation spatiale.

Les polygones sont synthétiques (carrés d'environ 1° placés dans l'emprise de
Madagascar) : aucun test ne dépend de `data/geo/*.geojson`, produit par
`tools/fetch_boundaries.py`.
"""

import sys
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geo_aggregate as ga  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def carre(lon_min, lat_min, cote=1.0):
    """Carré de `cote` degrés dont le coin sud-ouest est (lon_min, lat_min)."""
    return Polygon(
        [
            (lon_min, lat_min),
            (lon_min + cote, lat_min),
            (lon_min + cote, lat_min + cote),
            (lon_min, lat_min + cote),
        ]
    )


@pytest.fixture
def zones():
    """Trois zones disjointes autour d'Antananarivo, alignées d'ouest en est.

    A : lon 46-47, B : lon 48-49, C : lon 50-51 — toutes en latitude -19..-18.
    """
    return gpd.GeoDataFrame(
        {
            "code_zone": ["MG-A", "MG-B", "MG-C"],
            "nom_zone": ["Zone A", "Zone B", "Zone C"],
            "niveau": ["Région"] * 3,
            "code_parent": [None, None, None],
            "nom_parent": [None, None, None],
        },
        geometry=[carre(46, -19), carre(48, -19), carre(50, -19)],
        crs="EPSG:4326",
    )


def souscripteurs(lignes):
    """DataFrame de pré-souscripteurs au format attendu par `aggregate`."""
    return pd.DataFrame(
        lignes,
        columns=[
            "Adresse",
            "Type de compte",
            "Localité",
            "Ville",
            "Région",
            "lat",
            "lon",
            "precision",
        ],
    )


def etablissements(lignes):
    """DataFrame d'établissements partenaires au format attendu."""
    return pd.DataFrame(
        lignes,
        columns=[
            "Province",
            "Établissement",
            "Catégorie",
            "Coordonnées brutes",
            "lat",
            "lon",
        ],
    )


def sous_vide():
    return souscripteurs([])


def etab_vide():
    return etablissements([])


def un_souscripteur(localite, lat, lon, ville="Antananarivo", region="Analamanga"):
    return [
        f"{localite}, {ville}, {region}, Madagascar",
        "Particulier",
        localite,
        ville,
        region,
        lat,
        lon,
        "exacte",
    ]


def un_etablissement(nom, categorie, lat, lon, province="Antananarivo"):
    return [province, nom, categorie, f"{lat}, {lon}", lat, lon]


# --------------------------------------------------------------------------- #
# Contrat de sortie
# --------------------------------------------------------------------------- #


def test_colonnes_et_ordre_exacts(zones):
    zones_out, detail = ga._agreger(
        souscripteurs([un_souscripteur("Anosibe", -18.5, 46.5)]),
        etablissements([un_etablissement("Chez Domm", "Restaurant", -18.5, 46.6)]),
        zones,
    )
    assert list(zones_out.columns) == [
        "code_zone",
        "nom_zone",
        "niveau",
        "code_parent",
        "nom_parent",
        "inscrits",
        "localites",
        "etablissements",
        "etab_Boutique",
        "etab_Épicerie",
        "etab_Hôtel",
        "etab_Magasin",
        "etab_Restaurant",
        "etab_Supermarché",
        "ratio_inscrits_etab",
        "part_pct",
        "rattachement_approx_n",
        "localites_detail",
        "etablissements_detail",
        "geometry",
    ]
    assert list(detail.columns) == [
        "code_zone",
        "nom_zone",
        "niveau",
        "Localité",
        "Ville",
        "Région",
        "inscrits",
        "rattachement_approx",
    ]
    assert isinstance(zones_out, gpd.GeoDataFrame)
    assert zones_out.crs.to_string() == "EPSG:4326"


def test_entree_non_modifiee(zones):
    sous = souscripteurs([un_souscripteur("Anosibe", -18.5, 46.5)])
    etab = etablissements([un_etablissement("Tabet", "Boutique", -18.5, 48.5)])
    avant_sous, avant_etab = sous.copy(), etab.copy()
    colonnes_zones = list(zones.columns)

    ga._agreger(sous, etab, zones)

    pd.testing.assert_frame_equal(sous, avant_sous)
    pd.testing.assert_frame_equal(etab, avant_etab)
    assert list(zones.columns) == colonnes_zones


# --------------------------------------------------------------------------- #
# Rattachement par contenance
# --------------------------------------------------------------------------- #


def test_point_interieur_rattache_a_la_bonne_zone(zones):
    zones_out, detail = ga._agreger(
        souscripteurs([un_souscripteur("Ambondrona", -18.5, 48.5)]),
        etab_vide(),
        zones,
    )
    ligne = zones_out.set_index("code_zone").loc["MG-B"]
    assert ligne["inscrits"] == 1
    assert ligne["localites"] == 1
    assert ligne["rattachement_approx_n"] == 0
    assert zones_out.set_index("code_zone").loc["MG-A", "inscrits"] == 0
    assert len(detail) == 1
    assert detail.loc[0, "code_zone"] == "MG-B"
    assert detail.loc[0, "Localité"] == "Ambondrona"
    assert bool(detail.loc[0, "rattachement_approx"]) is False


# --------------------------------------------------------------------------- #
# Repli par proximité
# --------------------------------------------------------------------------- #


def test_point_hors_polygone_rattache_au_plus_proche(zones):
    """Point en mer à l'est : C (lon 50-51) est plus proche que B (48-49)."""
    zones_out, detail = ga._agreger(
        souscripteurs([un_souscripteur("Ilot", -18.5, 51.5)]),
        etab_vide(),
        zones,
    )
    par_code = zones_out.set_index("code_zone")
    assert par_code.loc["MG-C", "inscrits"] == 1
    assert par_code.loc["MG-C", "rattachement_approx_n"] == 1
    assert par_code.loc["MG-A", "inscrits"] == 0
    assert par_code.loc["MG-B", "inscrits"] == 0
    assert detail.loc[0, "code_zone"] == "MG-C"
    assert bool(detail.loc[0, "rattachement_approx"]) is True


def test_le_plus_proche_gagne_dans_les_deux_sens(zones):
    """Deux distances différentes de chaque côté : la plus courte doit gagner.

    Point 1 : lon 45,9 -> 0,1° de A, 2,1° de B.
    Point 2 : lon 49,5 mais latitude -20 (au sud) -> plus proche de B que de C.
    """
    zones_out, _ = ga._agreger(
        souscripteurs(
            [
                un_souscripteur("Ouest", -18.5, 45.9),
                un_souscripteur("Sud", -20.0, 48.9),
            ]
        ),
        etab_vide(),
        zones,
    )
    par_code = zones_out.set_index("code_zone")
    assert par_code.loc["MG-A", "inscrits"] == 1
    assert par_code.loc["MG-B", "inscrits"] == 1
    assert par_code.loc["MG-C", "inscrits"] == 0
    assert par_code["rattachement_approx_n"].sum() == 2


def test_pas_d_avertissement_de_crs_geographique(zones):
    """`sjoin_nearest` doit tourner en CRS projeté : aucun UserWarning attendu."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        ga._agreger(
            souscripteurs([un_souscripteur("Ilot", -18.5, 51.5)]),
            etablissements([un_etablissement("Ilot Shop", "Boutique", -18.5, 45.0)]),
            zones,
        )


# --------------------------------------------------------------------------- #
# Zones vides
# --------------------------------------------------------------------------- #


def test_zone_sans_point_presente_et_a_zero(zones):
    zones_out, _ = ga._agreger(
        souscripteurs([un_souscripteur("Anosibe", -18.5, 46.5)]),
        etab_vide(),
        zones,
    )
    assert len(zones_out) == 3
    vide = zones_out.set_index("code_zone").loc["MG-C"]
    assert vide["inscrits"] == 0
    assert vide["localites"] == 0
    assert vide["etablissements"] == 0
    assert vide["ratio_inscrits_etab"] is None
    assert vide["localites_detail"] == ""
    assert vide["etablissements_detail"] == ""
    assert vide["part_pct"] == 0.0
    assert vide.geometry is not None


# --------------------------------------------------------------------------- #
# Conservation des totaux
# --------------------------------------------------------------------------- #


def test_conservation_du_total_zones_et_detail(zones):
    lignes = [
        un_souscripteur("Anosibe", -18.5, 46.5),
        un_souscripteur("Anosibe", -18.6, 46.4),
        un_souscripteur("Itaosy", -18.2, 46.9),
        un_souscripteur("Ambondrona", -18.5, 48.5),
        un_souscripteur("Ilot", -18.5, 55.0),  # en mer, rattaché par proximité
    ]
    zones_out, detail = ga._agreger(souscripteurs(lignes), etab_vide(), zones)
    assert zones_out["inscrits"].sum() == 5
    assert detail["inscrits"].sum() == 5
    assert zones_out.set_index("code_zone").loc["MG-A", "localites"] == 2


def test_conservation_avec_lignes_non_geolocalisees(zones):
    lignes = [
        un_souscripteur("Anosibe", -18.5, 46.5),
        un_souscripteur("Sans coordonnées", None, None),
        un_souscripteur("Latitude seule", -18.5, None),
        un_souscripteur("Illisible", "n/a", "n/a"),
        un_souscripteur("Ambondrona", -18.5, 48.5),
    ]
    sous = souscripteurs(lignes)
    geolocalises = 2
    zones_out, detail = ga._agreger(sous, etab_vide(), zones)
    assert zones_out["inscrits"].sum() == geolocalises
    assert detail["inscrits"].sum() == geolocalises
    assert "Sans coordonnées" not in set(detail["Localité"])


def test_part_pct_somme_a_cent(zones):
    lignes = [un_souscripteur(f"L{i}", -18.5, 46.5) for i in range(7)]
    lignes += [un_souscripteur("Ambondrona", -18.5, 48.5)] * 3
    lignes += [un_souscripteur("Est", -18.5, 50.5)] * 5
    zones_out, _ = ga._agreger(souscripteurs(lignes), etab_vide(), zones)
    assert zones_out["part_pct"].sum() == pytest.approx(100.0, abs=0.1)
    # 7 / 15 = 46,666… -> 46,67 attendu.
    assert zones_out.set_index("code_zone").loc["MG-A", "part_pct"] == pytest.approx(
        46.67, abs=0.01
    )


def test_part_pct_somme_a_cent_sur_beaucoup_de_zones():
    """~1600 zones : l'arrondi indépendant dériverait, le plus fort reste non."""
    polygones, codes = [], []
    for i in range(1600):
        lon = 44.0 + (i % 40) * 0.15
        lat = -25.0 + (i // 40) * 0.15
        polygones.append(carre(lon, lat, 0.1))
        codes.append(f"Z{i:04d}")
    zones = gpd.GeoDataFrame(
        {
            "code_zone": codes,
            "nom_zone": codes,
            "niveau": ["Commune"] * 1600,
            "code_parent": [None] * 1600,
            "nom_parent": [None] * 1600,
        },
        geometry=polygones,
        crs="EPSG:4326",
    )
    lignes = []
    for i in range(0, 1600, 3):  # un point au centre d'une commune sur trois
        centre = polygones[i].centroid
        lignes.append(un_souscripteur(f"L{i}", centre.y, centre.x))
    zones_out, _ = ga._agreger(souscripteurs(lignes), etab_vide(), zones)
    assert zones_out["inscrits"].sum() == len(lignes)
    assert zones_out["part_pct"].sum() == pytest.approx(100.0, abs=0.1)


# --------------------------------------------------------------------------- #
# Ratio et ventilation par catégorie
# --------------------------------------------------------------------------- #


def test_ratio_none_sans_etablissement(zones):
    zones_out, _ = ga._agreger(
        souscripteurs([un_souscripteur("Anosibe", -18.5, 46.5)] * 4),
        etab_vide(),
        zones,
    )
    par_code = zones_out.set_index("code_zone")
    for code in ("MG-A", "MG-B", "MG-C"):
        valeur = par_code.loc[code, "ratio_inscrits_etab"]
        assert valeur is None
        assert valeur != float("inf")
    assert not any(
        isinstance(v, float) and v == float("inf")
        for v in zones_out["ratio_inscrits_etab"]
    )


def test_ratio_et_ventilation_par_categorie(zones):
    zones_out, _ = ga._agreger(
        souscripteurs([un_souscripteur("Anosibe", -18.5, 46.5)] * 6),
        etablissements(
            [
                un_etablissement("R1", "Restaurant", -18.4, 46.4),
                un_etablissement("R2", "Restaurant", -18.6, 46.6),
                un_etablissement("R3", "Restaurant", -18.7, 46.7),
                un_etablissement("H1", "Hôtel", -18.3, 46.3),
                un_etablissement("B1", "Boutique", -18.5, 48.5),
            ]
        ),
        zones,
    )
    a = zones_out.set_index("code_zone").loc["MG-A"]
    assert a["etablissements"] == 4
    assert a["etab_Restaurant"] == 3
    assert a["etab_Hôtel"] == 1
    assert a["etab_Boutique"] == 0
    assert a["ratio_inscrits_etab"] == pytest.approx(1.5)
    assert a["etablissements_detail"] == "Restaurant 3 · Hôtel 1"
    b = zones_out.set_index("code_zone").loc["MG-B"]
    assert b["etab_Boutique"] == 1
    assert b["etablissements_detail"] == "Boutique 1"
    assert b["inscrits"] == 0
    # Zone avec un partenaire mais aucun inscrit : ratio défini et nul, pas None.
    assert b["ratio_inscrits_etab"] == pytest.approx(0.0)
    assert b["ratio_inscrits_etab"] is not None


def test_etablissements_sans_coordonnees_ignores(zones):
    zones_out, _ = ga._agreger(
        sous_vide(),
        etablissements(
            [
                un_etablissement("Ok", "Hôtel", -18.5, 46.5),
                un_etablissement("Sans coords", "Hôtel", None, None),
            ]
        ),
        zones,
    )
    assert zones_out["etablissements"].sum() == 1


# --------------------------------------------------------------------------- #
# Libellés de popup
# --------------------------------------------------------------------------- #


def test_localites_detail_ordonne_tronque_et_echappe(zones):
    lignes = []
    effectifs = {
        "Anosibe": 55,
        "Itaosy": 22,
        "C": 9,
        "D": 8,
        "E": 7,
        "F": 6,
        "G": 5,
        "H": 4,
    }
    for nom, nombre in effectifs.items():
        lignes += [un_souscripteur(nom, -18.5, 46.5)] * nombre
    lignes += [un_souscripteur("<script>x</script>", -18.5, 46.5)]
    zones_out, _ = ga._agreger(souscripteurs(lignes), etab_vide(), zones)
    texte = zones_out.set_index("code_zone").loc["MG-A", "localites_detail"]
    assert texte.startswith("Anosibe (55) · Itaosy (22) · C (9)")
    # 9 localités, 6 affichées puis le résumé.
    assert texte.endswith("· et 3 autres")
    assert texte.count(" · ") == 6
    assert "<script>" not in texte

    zones_out2, _ = ga._agreger(
        souscripteurs(
            [un_souscripteur("<b>Anosibe</b>", -18.5, 46.5)]
        ),
        etab_vide(),
        zones,
    )
    assert (
        zones_out2.set_index("code_zone").loc["MG-A", "localites_detail"]
        == "&lt;b&gt;Anosibe&lt;/b&gt; (1)"
    )


def test_localites_detail_singulier(zones):
    """Sept localités : une seule en surplus, « et 1 autre » au singulier."""
    lignes = []
    for rang, nom in enumerate("ABCDEFG"):
        lignes += [un_souscripteur(nom, -18.5, 46.5)] * (10 - rang)
    zones_out, _ = ga._agreger(souscripteurs(lignes), etab_vide(), zones)
    texte = zones_out.set_index("code_zone").loc["MG-A", "localites_detail"]
    assert texte == "A (10) · B (9) · C (8) · D (7) · E (6) · F (5) · et 1 autre"


def test_categorie_hors_referentiel_comptee_dans_le_total(zones):
    """« Non renseignée » n'a pas de colonne `etab_*` mais reste dans le total."""
    zones_out, _ = ga._agreger(
        sous_vide(),
        etablissements(
            [
                un_etablissement("Ok", "Restaurant", -18.5, 46.5),
                un_etablissement("Inconnu", None, -18.6, 46.6),
                un_etablissement("Exotique", "Pharmacie", -18.7, 46.7),
            ]
        ),
        zones,
    )
    a = zones_out.set_index("code_zone").loc["MG-A"]
    assert a["etablissements"] == 3
    assert a["etab_Restaurant"] == 1
    assert sum(int(a[f"etab_{c}"]) for c in ga.CATEGORIES) == 1
    assert a["etablissements_detail"] == "Restaurant 1 · Pharmacie 1 · Non renseignée 1"
    assert all(
        pd.api.types.is_integer_dtype(zones_out[f"etab_{c}"]) for c in ga.CATEGORIES
    )
    for colonne in ("inscrits", "localites", "etablissements", "rattachement_approx_n"):
        assert pd.api.types.is_integer_dtype(zones_out[colonne])


def test_detail_trie_par_zone_puis_inscrits(zones):
    lignes = [un_souscripteur("Petite", -18.5, 46.5)]
    lignes += [un_souscripteur("Grande", -18.6, 46.6)] * 3
    lignes += [un_souscripteur("Est", -18.5, 50.5)] * 2
    _, detail = ga._agreger(souscripteurs(lignes), etab_vide(), zones)
    assert list(detail["code_zone"]) == ["MG-A", "MG-A", "MG-C"]
    assert list(detail["Localité"]) == ["Grande", "Petite", "Est"]
    assert list(detail["inscrits"]) == [3, 1, 2]
    assert detail["rattachement_approx"].dtype == bool


# --------------------------------------------------------------------------- #
# Entrées dégénérées
# --------------------------------------------------------------------------- #


def test_entree_entierement_vide(zones):
    zones_out, detail = ga._agreger(sous_vide(), etab_vide(), zones)
    assert len(zones_out) == 3
    assert zones_out["inscrits"].sum() == 0
    assert zones_out["etablissements"].sum() == 0
    assert list(zones_out["localites_detail"]) == ["", "", ""]
    assert all(v is None for v in zones_out["ratio_inscrits_etab"])
    assert zones_out["part_pct"].sum() == 0.0
    assert detail.empty
    assert list(detail.columns) == ga.COLONNES_DETAIL


def test_entree_sans_aucune_coordonnee_exploitable(zones):
    lignes = [
        un_souscripteur("X", None, None),
        un_souscripteur("Y", float("nan"), 46.5),
    ]
    zones_out, detail = ga._agreger(souscripteurs(lignes), etab_vide(), zones)
    assert zones_out["inscrits"].sum() == 0
    assert detail.empty


def test_localite_absente_remplacee_par_non_renseignee(zones):
    sous = souscripteurs([un_souscripteur(None, -18.5, 46.5)])
    zones_out, detail = ga._agreger(sous, etab_vide(), zones)
    assert zones_out.set_index("code_zone").loc["MG-A", "inscrits"] == 1
    assert detail.loc[0, "Localité"] == ga.NON_RENSEIGNE


# --------------------------------------------------------------------------- #
# Chargement des géométries
# --------------------------------------------------------------------------- #


def test_chemin_zones_et_niveau_invalide():
    assert ga.chemin_zones("Commune").name == "mdg_adm3.geojson"
    assert ga.chemin_zones("adm1").name == "mdg_adm1.geojson"
    with pytest.raises(ValueError):
        ga.chemin_zones("Fokontany")


def test_load_zones_absent_leve_file_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(ga, "GEO_DIR", tmp_path)
    assert ga.zones_disponibles() is False
    with pytest.raises(FileNotFoundError):
        ga.load_zones("Région")
    with pytest.raises(FileNotFoundError):
        ga.aggregate(sous_vide(), etab_vide(), "Région")


def test_charger_zones_relit_le_geojson(tmp_path, zones, monkeypatch):
    monkeypatch.setattr(ga, "GEO_DIR", tmp_path)
    for niveau, suffixe in ga.NIVEAUX.items():
        copie = zones.copy()
        copie["niveau"] = niveau
        copie.to_file(tmp_path / f"mdg_{suffixe}.geojson", driver="GeoJSON")

    assert ga.zones_disponibles() is True
    lues = ga.load_zones("District")
    assert list(lues.columns) == ga.COLONNES_ZONE + ["geometry"]
    assert list(lues["code_zone"]) == ["MG-A", "MG-B", "MG-C"]
    assert lues["code_parent"].isna().all()
    assert lues.crs.to_string() == "EPSG:4326"

    zones_out, _ = ga.aggregate(
        souscripteurs([un_souscripteur("Anosibe", -18.5, 46.5)]),
        etab_vide(),
        "District",
    )
    assert zones_out.set_index("code_zone").loc["MG-A", "inscrits"] == 1


def test_zones_sans_proprietes_attendues_rejetees():
    brut = gpd.GeoDataFrame({"nom": ["A"]}, geometry=[carre(46, -19)], crs="EPSG:4326")
    with pytest.raises(ValueError):
        ga._agreger(sous_vide(), etab_vide(), brut)


def test_zones_reprojetees_en_wgs84(zones):
    projetees = zones.to_crs("EPSG:32738")
    zones_out, _ = ga._agreger(
        souscripteurs([un_souscripteur("Anosibe", -18.5, 46.5)]), etab_vide(), projetees
    )
    assert zones_out.crs.to_string() == "EPSG:4326"
    assert zones_out.set_index("code_zone").loc["MG-A", "inscrits"] == 1
