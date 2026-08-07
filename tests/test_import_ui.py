"""
Test de bout en bout de la section « Importer la liste des pré-inscrits ».

L'application est exécutée par `AppTest`, le harnais de Streamlit : mêmes
widgets, même enchaînement, sans navigateur. Deux garde-fous, sans lesquels ce
test toucherait au vrai dépôt :

- les chemins d'écriture de `pre_inscrits` sont redirigés vers `tmp_path` ;
- le géocodeur est remplacé par une fonction locale — aucun appel à Nominatim.

Le premier point suppose que les fonctions d'écriture résolvent leur chemin à
l'appel (`chemin = chemin or AGREGAT`) et non dans leur signature : c'est ce
qui rend l'emplacement des données interchangeable.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import pre_inscrits as pi  # noqa: E402

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

FICHIER = (
    "first Name,last Name,Adresse,phone,email,Account\n"
    "Jean,Rakoto,\"ALAROBIA, ANTANANARIVO, ANALAMANGA\",034,j@x.mg,Particulier\n"
    "Koto,Rasoa,\"Alarobia, Antananarivo, Analamanga, Madagascar\",033,k@x.mg,Marchand\n"
    "Bema,Naivo,tamatave,032,b@x.mg,Epicerie\n"
    "Soa,Hery,Ambatatolampy,031,s@x.mg,Particulier\n"
    "Fara,Lala,\"Ambatolampy, Vakinankaratra, Madagascar\",030,f@x.mg,Particulier\n"
    "Vola,Tiana,vola.tiana@gmail.com,039,v@x.mg,Particulier\n"
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Application prête à recevoir un import, isolée du dépôt."""
    monkeypatch.setattr(pi, "AGREGAT", tmp_path / "agregat.csv")
    monkeypatch.setattr(pi, "CACHE_GEO", tmp_path / "cache.csv")
    monkeypatch.setattr(pi, "CORRESPONDANCES", tmp_path / "correspondances.csv")

    appels = []

    def faux_geocodeur(adresse, **_):
        appels.append(adresse)
        return {
            "lat": -18.15,
            "lon": 49.41,
            "precision": "exacte",
            "correspondance": adresse,
        }

    monkeypatch.setattr(pi, "geocoder", faux_geocodeur)

    at = AppTest.from_file(str(RACINE / "app.py"), default_timeout=180)
    at.geocodes = appels
    return at


def _deposer(at, contenu=FICHIER):
    at.run()
    at.file_uploader[0].set_value(("inscrits.csv", contenu.encode("utf-8"), "text/csv"))
    return at.run()


def test_le_fichier_depose_est_analyse_avant_toute_ecriture(app, tmp_path):
    at = _deposer(app)
    assert not at.exception

    mesures = {m.label: m.value for m in at.metric}
    assert mesures["Lignes lues"] == "6"
    # Trois lignes réécrites : « ALAROBIA… » rejoint la graphie déjà connue,
    # « tamatave » devient « Toamasina », l'e-mail devient « Adresse non
    # renseignée ». Restent 5 libellés distincts, dont 4 géocodables.
    assert mesures["Libellés uniformisés"] == "3"
    assert mesures["Adresses distinctes"] == "5"
    assert mesures["Adresses à géocoder"] == "4"

    # Rien n'a encore été écrit ni géocodé : l'analyse est sans effet de bord.
    assert not (tmp_path / "agregat.csv").exists()
    assert not (tmp_path / "cache.csv").exists()
    assert at.geocodes == []


def test_les_fusions_sont_proposees_et_jamais_cochees_d_office(app):
    at = _deposer(app)
    # « Ambatatolampy » et « Ambatolampy, Vakinankaratra » se ressemblent :
    # la proposition existe, mais la décision reste à prendre.
    assert len(at.checkbox) >= 1
    assert all(not case.value for case in at.checkbox)
    assert any("Ambatolampy" in case.label for case in at.checkbox)


def test_import_ecrit_les_trois_fichiers_et_geocode_les_nouvelles(app, tmp_path):
    at = _deposer(app)
    at.button[0].click().run()
    assert not at.exception

    agregat = pd.read_csv(tmp_path / "agregat.csv", dtype=str)
    assert agregat["Inscrits"].astype(int).sum() == 6
    # L'e-mail a bien été neutralisé, et les deux graphies d'Alarobia réunies.
    assert pi.ADRESSE_INCONNUE in set(agregat["Adresse"])
    alarobia = agregat[agregat["Adresse"].str.startswith("Alarobia")]
    assert alarobia["Inscrits"].astype(int).sum() == 2

    cache = pi.charger_cache_geo(tmp_path / "cache.csv")
    # « Adresse non renseignée » n'est jamais soumise au géocodeur.
    assert pi.ADRESSE_INCONNUE not in cache
    assert set(app.geocodes) == set(cache)
    assert len(cache) == 4

    contenu = (tmp_path / "agregat.csv").read_text(encoding="utf-8")
    for donnee in ("Jean", "Rakoto", "034", "j@x.mg", "gmail"):
        assert donnee not in contenu


def test_fusion_confirmee_regroupe_et_se_conserve(app, tmp_path):
    at = _deposer(app)
    case = next(c for c in at.checkbox if "Ambatolampy" in c.label)
    case.check().run()
    at.button[0].click().run()
    assert not at.exception

    agregat = pd.read_csv(tmp_path / "agregat.csv", dtype=str)
    assert "Ambatatolampy" not in set(agregat["Adresse"])
    ambatolampy = agregat[agregat["Adresse"].str.startswith("Ambatolampy")]
    assert ambatolampy["Inscrits"].astype(int).sum() == 2

    # La décision est mémorisée : un second import ne la redemandera pas.
    table = pi.charger_correspondances(tmp_path / "correspondances.csv")
    assert table[pi.cle("Ambatatolampy")].startswith("Ambatolampy")


def test_second_import_ne_regeocode_rien(app, tmp_path):
    at = _deposer(app)
    at.button[0].click().run()
    premier = list(app.geocodes)
    assert premier

    app.geocodes.clear()
    at = _deposer(app)
    at.button[0].click().run()
    assert not at.exception
    # Toutes les adresses sont déjà dans le cache : aucune requête réseau.
    assert app.geocodes == []
