"""
Tests de la lecture du Sheet utilisée par l'iframe (`static/embed/build.py`).

Aucun accès réseau : les CSV sont écrits à la main. Ces règles sont dupliquées
en JavaScript dans `static/embed/assets/data.js` pour la relecture en direct — toute
correction ici doit y être reportée.
"""

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
# Instantané
# --------------------------------------------------------------------------- #


def test_instantane_est_du_javascript_lisible():
    """Le fichier généré doit rester une simple affectation de variable."""
    rendu = embed_build.render(lire(ENTETE + 'Toamasina,Chez X,Restaurant,"-18.15, 49.41"\n'), "2026-01-01T00:00:00Z")
    assert rendu.startswith("/*")
    assert "window.EARIARY_SNAPSHOT = {" in rendu
    assert rendu.rstrip().endswith("};")
    assert "Chez X" in rendu  # accents et guillemets non échappés en \uXXXX


def test_instantane_du_depot_est_coherent():
    """L'instantané versionné doit être lisible et non vide."""
    fichier = RACINE / "static" / "embed" / "assets" / "etablissements.js"
    contenu = fichier.read_text(encoding="utf-8")
    assert "window.EARIARY_SNAPSHOT" in contenu
    assert '"etablissements"' in contenu
