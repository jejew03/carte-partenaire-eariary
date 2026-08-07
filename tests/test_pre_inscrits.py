"""
Tests de l'import des pré-inscrits (`pre_inscrits.py`).

Aucun accès réseau : le géocodeur reçoit une fonction d'interrogation factice,
et la pause entre requêtes est mise à zéro. Les tests d'écriture travaillent
dans `tmp_path` — jamais dans `data/`, dont les fichiers sont versionnés.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import pre_inscrits as pi  # noqa: E402


# --------------------------------------------------------------------------- #
# Uniformisation des adresses
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "brut, attendu",
    [
        # Casse : une saisie tout en capitales est ramenée à l'usage.
        ("ANTANANARIVO", "Antananarivo"),
        ("antananarivo", "Antananarivo"),
        # Une casse composée est un choix de saisie : on n'y touche pas.
        ("Ambato-Boeny, Boeny", "Ambato-Boeny, Boeny, Madagascar"),
        # Espaces, virgules collées, ponctuation de fin.
        ("  Anosy ,   Antananarivo ,Analamanga  ", "Anosy, Antananarivo, Analamanga, Madagascar"),
        ("Alarobia,,Antananarivo", "Alarobia, Antananarivo, Madagascar"),
        # Noms usuels ramenés au nom officiel.
        ("Tamatave", "Toamasina"),
        ("tana, analamanga", "Antananarivo, Analamanga, Madagascar"),
        ("fort dauphin, anosy", "Tolagnaro, Anosy, Madagascar"),
        # Le pays est normalisé plutôt que dupliqué.
        ("Alarobia, Antananarivo, MADAGASIKARA", "Alarobia, Antananarivo, Madagascar"),
    ],
)
def test_regles_d_uniformisation(brut, attendu):
    assert pi.normaliser_adresse(brut) == attendu


def test_localite_seule_ne_recoit_pas_le_pays():
    """Lui coller « , Madagascar » la ferait passer pour une adresse structurée,
    que le géocodeur traiterait alors comme sûre."""
    assert pi.normaliser_adresse("Ambaranjana") == "Ambaranjana"
    assert pi.normaliser_adresse("  ambaranjana ") == "Ambaranjana"


@pytest.mark.parametrize(
    "brut",
    ["", "   ", "nan", "None", "jean.dupont@gmail.com", "contact chez yahoo.fr", ",,,"],
)
def test_adresses_sans_valeur_geographique(brut):
    assert pi.normaliser_adresse(brut) == pi.ADRESSE_INCONNUE


def test_uniformisation_idempotente():
    """Réimporter un fichier déjà uniformisé ne doit rien déplacer."""
    for brut in ["TANA, analamanga", "Ambaranjana", "Anosy , Antananarivo", ""]:
        une_fois = pi.normaliser_adresse(brut)
        assert pi.normaliser_adresse(une_fois) == une_fois


def test_corpus_existant_inchange():
    """Les règles ne doivent pas réécrire les adresses déjà géocodées.

    Une seule réécriture invaliderait la clé du cache : l'adresse repartirait
    en géocodage et se dédoublerait sur la carte.
    """
    agregat = pi.lire_agregat()
    if agregat.empty:
        pytest.skip("data/pre_souscripteurs_agreges.csv absent")
    for adresse in set(agregat["Adresse"]):
        assert pi.normaliser_adresse(adresse) == adresse


@pytest.mark.parametrize(
    "brut, attendu",
    [
        ("Particulier", "Particulier"),
        ("  marchand ", "Non renseigné"),  # la casse d'un type est significative
        ("Epicerie", "Épicerie"),
        ("Épicerie", "Épicerie"),
        ("truc@example.com", "Non renseigné"),
        ("", "Non renseigné"),
    ],
)
def test_normalisation_des_types_de_compte(brut, attendu):
    assert pi.normaliser_compte(brut) == attendu


# --------------------------------------------------------------------------- #
# Lecture du fichier déposé
# --------------------------------------------------------------------------- #


ENTETE = "first Name,last Name,Adresse,phone,email,Account\n"
LIGNE = "Jean,Rakoto,\"Alarobia, Antananarivo, Analamanga\",034,j@x.mg,Particulier\n"


def test_lecture_csv_et_detection_des_colonnes():
    df = pi.lire_fichier((ENTETE + LIGNE).encode("utf-8"), "inscrits.csv")
    assert pi.colonnes_utiles(df) == ("Adresse", "Account")


@pytest.mark.parametrize(
    "texte, encodage",
    [
        ("Adresse;Account\nTAMATAVE;Particulier\n", "utf-8"),
        ("Adresse\tAccount\nTAMATAVE\tParticulier\n", "utf-8"),
        ("Adresse,Account\nTAMATAVE,Particulier\n", "utf-8-sig"),
        ("Adresse,Account\nTaméatave,Particulier\n", "cp1252"),
    ],
)
def test_separateurs_et_encodages(texte, encodage):
    """Séparateur imposé et encodage supposé : première cause d'import raté."""
    df = pi.lire_fichier(texte.encode(encodage), "inscrits.csv")
    assert list(df.columns) == ["Adresse", "Account"]
    assert len(df) == 1


def test_preparation_ne_garde_que_deux_colonnes():
    """Noms, téléphones et e-mails ne doivent pas survivre à la préparation."""
    df = pi.lire_fichier((ENTETE + LIGNE).encode("utf-8"), "inscrits.csv")
    prepare = pi.preparer(df, "Adresse", "Account")
    assert list(prepare.columns) == ["Adresse importée", "Adresse", "Type de compte"]
    contenu = prepare.to_csv(index=False)
    for donnee in ("Jean", "Rakoto", "034", "j@x.mg"):
        assert donnee not in contenu


def test_preparation_sans_colonne_de_compte():
    df = pi.lire_fichier(b"Adresse\nTAMATAVE\n", "inscrits.csv")
    prepare = pi.preparer(df, "Adresse", None)
    assert list(prepare["Type de compte"]) == ["Non renseigné"]


# --------------------------------------------------------------------------- #
# Correspondances retenues
# --------------------------------------------------------------------------- #


def test_correspondances_aller_retour(tmp_path):
    chemin = tmp_path / "adresses_normalisees.csv"
    pi.enregistrer_correspondances({"ambatatolampy": "Ambatolampy, Vakinankaratra, Madagascar"}, chemin)
    assert pi.charger_correspondances(chemin) == {
        "ambatatolampy": "Ambatolampy, Vakinankaratra, Madagascar"
    }


def test_correspondances_absentes(tmp_path):
    assert pi.charger_correspondances(tmp_path / "rien.csv") == {}


def test_application_insensible_a_la_casse_et_aux_accents():
    table = {pi.cle("Ambatatolampy"): "Ambatolampy, Vakinankaratra, Madagascar"}
    serie = pd.Series(["AMBATATOLAMPY", "Ambatatolampy", "Autre chose"])
    assert list(pi.appliquer_correspondances(serie, table)) == [
        "Ambatolampy, Vakinankaratra, Madagascar",
        "Ambatolampy, Vakinankaratra, Madagascar",
        "Autre chose",
    ]


# --------------------------------------------------------------------------- #
# Suggestions de fusion
# --------------------------------------------------------------------------- #


def test_meme_localite_contexte_different():
    effectifs = {
        "Mahitsy, Analamanga, Madagascar": 2,
        "Mahitsy, Antananarivo, Analamanga, Madagascar": 5,
    }
    (suggestion,) = pi.suggerer_fusions(effectifs)
    assert suggestion["motif"] == "même localité, contexte différent"
    # Le plus détaillé l'emporte à défaut de géocodage exact.
    assert suggestion["retenue"] == "Mahitsy, Antananarivo, Analamanga, Madagascar"
    assert suggestion["variantes"] == ["Mahitsy, Analamanga, Madagascar"]
    assert suggestion["inscrits"] == 7


def test_orthographes_proches():
    effectifs = {"Ambatatolampy": 1, "Ambatolampy, Vakinankaratra, Madagascar": 3}
    (suggestion,) = pi.suggerer_fusions(effectifs)
    assert suggestion["motif"] == "orthographes proches"
    assert suggestion["retenue"] == "Ambatolampy, Vakinankaratra, Madagascar"


def test_le_geocodage_exact_prime_sur_le_detail():
    effectifs = {"Anosy, Antananarivo, Analamanga, Madagascar": 1, "Anosy": 9}
    precisions = {"Anosy": "exacte", "Anosy, Antananarivo, Analamanga, Madagascar": "approchée"}
    (suggestion,) = pi.suggerer_fusions(effectifs, precisions)
    assert suggestion["retenue"] == "Anosy"


def test_libelles_distincts_ne_sont_pas_proposes():
    effectifs = {"Toamasina, Atsinanana, Madagascar": 3, "Mahajanga, Boeny, Madagascar": 2}
    assert pi.suggerer_fusions(effectifs) == []


def test_adresse_inconnue_hors_des_suggestions():
    effectifs = {pi.ADRESSE_INCONNUE: 12, "Toamasina, Atsinanana, Madagascar": 1}
    assert pi.suggerer_fusions(effectifs) == []


def test_suggestions_du_corpus_reel_restent_peu_nombreuses():
    """Une liste de propositions trop longue ne serait jamais relue."""
    agregat = pi.lire_agregat()
    if agregat.empty:
        pytest.skip("data/pre_souscripteurs_agreges.csv absent")
    effectifs = {
        adresse: int(total)
        for adresse, total in agregat.groupby("Adresse")["Inscrits"]
        .apply(lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum())
        .items()
    }
    suggestions = pi.suggerer_fusions(effectifs)
    assert 0 < len(suggestions) <= 20


# --------------------------------------------------------------------------- #
# Agrégat
# --------------------------------------------------------------------------- #


def test_agregat_compte_par_adresse_et_par_type():
    prepare = pd.DataFrame(
        {
            "Adresse importée": ["a"] * 4,
            "Adresse": ["Toamasina", "Toamasina", "Toamasina", "Mahajanga"],
            "Type de compte": ["Particulier", "Particulier", "Marchand", "Particulier"],
        }
    )
    agregat = pi.agreger(prepare)
    assert list(agregat.columns) == ["Adresse", "Account", "Inscrits"]
    assert agregat["Inscrits"].sum() == 4
    ligne = agregat[(agregat["Adresse"] == "Toamasina") & (agregat["Account"] == "Particulier")]
    assert int(ligne["Inscrits"].iloc[0]) == 2


def test_agregat_aller_retour(tmp_path):
    chemin = tmp_path / "agregat.csv"
    agregat = pd.DataFrame(
        {"Adresse": ["Toamasina"], "Account": ["Particulier"], "Inscrits": [3]}
    )
    pi.enregistrer_agregat(agregat, chemin)
    relu = pi.lire_agregat(chemin)
    assert list(relu["Adresse"]) == ["Toamasina"] and list(relu["Inscrits"]) == ["3"]


def test_resume_ne_liste_que_les_libelles_reecrits():
    prepare = pd.DataFrame(
        {
            "Adresse importée": ["TAMATAVE", "Ambaranjana"],
            "Adresse": ["Toamasina", "Ambaranjana"],
            "Type de compte": ["Particulier", "Particulier"],
        }
    )
    resume = pi.resume_uniformisation(prepare)
    assert len(resume) == 1
    assert resume.iloc[0]["Adresse importée"] == "TAMATAVE"
    assert resume.iloc[0]["Adresse retenue"] == "Toamasina"


# --------------------------------------------------------------------------- #
# Géocodage — sans réseau
# --------------------------------------------------------------------------- #


def _reponse(lat="-18.15", lon="49.41", nom="quelque part"):
    return [{"lat": lat, "lon": lon, "display_name": nom}]


def test_adresse_structuree_resolue_du_premier_coup():
    resultat = pi.geocoder(
        "Alarobia, Antananarivo, Analamanga, Madagascar",
        requete=lambda texte: _reponse(),
        pause=0,
    )
    assert resultat["precision"] == "exacte"
    assert resultat["lat"] == -18.15


def test_repli_sur_une_variante_plus_large():
    """Le premier niveau échoue, le suivant répond : le point est approché."""
    appels = []

    def requete(texte):
        appels.append(texte)
        return [] if len(appels) == 1 else _reponse()

    resultat = pi.geocoder("Anosibe, Antananarivo, Analamanga", requete=requete, pause=0)
    assert resultat["precision"] == "approchée"
    assert appels == [
        "Anosibe, Antananarivo, Analamanga, Madagascar",
        "Antananarivo, Analamanga, Madagascar",
    ]


def test_adresse_sans_contexte_reste_incertaine():
    """Restreinte à Madagascar, la recherche renvoie toujours quelque chose."""
    resultat = pi.geocoder("Paris", requete=lambda texte: _reponse(), pause=0)
    assert resultat["precision"] == "incertaine"


def test_introuvable():
    resultat = pi.geocoder("Zzz, Yyy", requete=lambda texte: [], pause=0)
    assert resultat["precision"] == "introuvable"
    assert resultat["lat"] == ""


def test_panne_reseau_n_est_pas_un_introuvable():
    """Distinction essentielle : un incident ne doit pas être mis en cache
    comme une réponse négative définitive."""
    resultat = pi.geocoder("Zzz, Yyy", requete=lambda texte: None, pause=0)
    assert resultat["precision"] == "erreur réseau"


def test_cache_aller_retour_et_adresses_a_geocoder(tmp_path):
    chemin = tmp_path / "cache.csv"
    cache = {
        "Toamasina": {
            "Adresse": "Toamasina",
            "lat": "-18.15",
            "lon": "49.41",
            "precision": "exacte",
            "correspondance": "Toamasina",
        }
    }
    pi.enregistrer_cache_geo(cache, chemin)
    relu = pi.charger_cache_geo(chemin)
    assert relu["Toamasina"]["precision"] == "exacte"

    a_faire = pi.adresses_a_geocoder(
        ["Toamasina", "Mahajanga", pi.ADRESSE_INCONNUE, ""], relu
    )
    assert a_faire == ["Mahajanga"]
