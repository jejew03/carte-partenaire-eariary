"""Import et uniformisation de la liste des pré-inscrits eAriary.

Ce module porte tout ce que l'import fait *hors interface* : lecture du
fichier déposé, uniformisation des adresses, suggestions de fusion, agrégation
anonyme et géocodage. `app.py` n'en garde que l'enchaînement et l'affichage,
`tools/geocode_souscripteurs.py` en réutilise le géocodage — les règles ne
vivent qu'ici.

Ce que l'import écrit dans `data/`, et rien d'autre :

    pre_souscripteurs_agreges.csv   effectifs par adresse et type de compte
    adresses_geocodees.csv          adresse -> latitude / longitude
    adresses_normalisees.csv        libellé importé -> libellé retenu

**Le fichier déposé n'est jamais écrit sur le disque.** Il contient des noms,
des téléphones et des e-mails ; seuls ces trois dérivés, qui n'identifient
personne, sont conservés — c'est la raison d'être de l'agrégat, et la raison
pour laquelle le classeur d'origine est exclu du dépôt (`.gitignore`).
"""

from __future__ import annotations

import csv
import difflib
import io
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_GEO = DATA_DIR / "adresses_geocodees.csv"
AGREGAT = DATA_DIR / "pre_souscripteurs_agreges.csv"
CORRESPONDANCES = DATA_DIR / "adresses_normalisees.csv"

COLONNES_CACHE = ["Adresse", "lat", "lon", "precision", "correspondance"]
COLONNES_CORRESPONDANCES = ["Adresse importée", "Adresse retenue"]

# Le champ « Adresse » recueille parfois une adresse e-mail (avec ou sans les
# points et l'arobase). Sans valeur géographique, et identifiant directement une
# personne, elle est neutralisée avant tout traitement.
EMAIL_LIKE = re.compile(
    r"@|(?:gmail|yahoo|hotmail|outlook|orange|moov|telma|esemahay)\.?(?:com|fr|mg)",
    re.IGNORECASE,
)
ADRESSE_INCONNUE = "Adresse non renseignée"

# Référentiel des types de compte. La colonne « Account » comporte elle aussi des
# saisies libres : tout ce qui en sort est ramené à « Non renseigné ».
COMPTES = ["Particulier", "Marchand", "Épicerie", "Grande Entreprise"]
COMPTE_INCONNU = "Non renseigné"
COMPTES_ALIAS = {"epicerie": "Épicerie", "particuliers": "Particulier"}

# Noms coloniaux et abréviations courantes. Une même ville écrite « Tamatave »
# ou « Toamasina » donne deux points sur la carte et deux lignes dans le
# récapitulatif : c'est le premier travail de l'uniformisation.
ALIAS_LIEUX = {
    "tananarive": "Antananarivo",
    "tana": "Antananarivo",
    "antananarivo ville": "Antananarivo",
    "tamatave": "Toamasina",
    "majunga": "Mahajanga",
    "diego": "Antsiranana",
    "diego suarez": "Antsiranana",
    "tulear": "Toliara",
    "tulear ville": "Toliara",
    "fort dauphin": "Tolagnaro",
    "taolagnaro": "Tolagnaro",
    "fianar": "Fianarantsoa",
    "nosy be": "Nosy Be",
}

PAYS = {"madagascar", "madagasikara", "mdg", "mada"}
PAYS_RETENU = "Madagascar"


# --------------------------------------------------------------------------- #
# Uniformisation
# --------------------------------------------------------------------------- #


def cle(texte) -> str:
    """Forme repliée servant à comparer deux libellés : sans accent ni ponctuation.

    C'est la clé de rapprochement, jamais ce qui s'affiche : « ANTANANARIVO »,
    « Antananarivo » et « antananarivo  » y deviennent la même chaîne.
    """
    texte = unicodedata.normalize("NFD", str(texte).lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


def _casse(mot: str) -> str:
    """Remet en capitale initiale un fragment saisi tout en haut ou tout en bas.

    Un fragment déjà composé — « Ambato-Boeny », « Ivato Aéroport » — est laissé
    tel quel : sa casse est un choix de saisie, pas un accident.
    """
    if not mot or (mot != mot.upper() and mot != mot.lower()):
        return mot
    return re.sub(
        r"[^\s\-']+",
        lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(),
        mot,
    )


def normaliser_adresse(valeur) -> str:
    """Libellé uniformisé d'une adresse : espaces, casse, alias, pays.

    Les règles sont volontairement conservatrices — elles ne rapprochent que ce
    qui est certain. Deux libellés qu'elles laissent distincts sans l'être
    vraiment (« Ambatatolampy » et « Ambatolampy ») relèvent de l'écran de
    fusion, où une personne tranche.
    """
    texte = str(valeur).strip()
    if not texte or texte.lower() in {"nan", "none"} or EMAIL_LIKE.search(texte):
        return ADRESSE_INCONNUE

    fragments = []
    for fragment in texte.split(","):
        fragment = re.sub(r"\s+", " ", fragment).strip(" .;:-")
        if not fragment:
            continue
        fragment = ALIAS_LIEUX.get(cle(fragment), _casse(fragment))
        fragments.append(fragment)

    if not fragments:
        return ADRESSE_INCONNUE

    # Le pays n'est ajouté qu'aux adresses qui portent déjà un contexte
    # administratif. Une localité seule (« Ambaranjana ») reste seule : lui
    # coller « , Madagascar » la ferait passer pour une adresse structurée
    # auprès du géocodeur, qui la traiterait alors comme sûre.
    if len(fragments) > 1:
        if cle(fragments[-1]) in PAYS:
            fragments[-1] = PAYS_RETENU
        else:
            fragments.append(PAYS_RETENU)

    return ", ".join(fragments)


def normaliser_compte(valeur) -> str:
    texte = re.sub(r"\s+", " ", str(valeur)).strip()
    texte = COMPTES_ALIAS.get(cle(texte), texte)
    return texte if texte in COMPTES else COMPTE_INCONNU


# --------------------------------------------------------------------------- #
# Lecture du fichier déposé
# --------------------------------------------------------------------------- #


def trouver_colonne(df: pd.DataFrame, *mots: str):
    """Nom de la première colonne dont l'intitulé contient un des mots-clés."""
    for colonne in df.columns:
        bas = str(colonne).lower()
        if any(mot in bas for mot in mots):
            return colonne
    return None


SEPARATEURS = ",;\t|"


def _decoder(contenu: bytes) -> str:
    """Texte du fichier, encodage deviné.

    `utf-8-sig` d'abord : il lit l'UTF-8 ordinaire *et* retire la marque d'ordre
    d'octets qu'Excel place en tête de ses exports — sans quoi la première
    colonne s'appellerait « ﻿Adresse » et ne serait plus reconnue.
    `latin-1` accepte n'importe quel octet : la boucle aboutit toujours.
    """
    for encodage in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return contenu.decode(encodage)
        except UnicodeDecodeError:
            continue
    return contenu.decode("utf-8", errors="replace")


def lire_fichier(contenu: bytes, nom: str) -> pd.DataFrame:
    """Lit le fichier déposé — CSV ou Excel — sans rien présumer de sa forme.

    Un séparateur imposé et un encodage supposé sont la première cause d'un
    import qui « ne marche pas » : les deux sont donc devinés. La liste des
    séparateurs candidats est explicite, car le renifleur laissé libre choisit
    des absurdités sur un fichier à une seule colonne — sur « Adresse\\nTAMATAVE »,
    il retient « s » et rend trois colonnes.
    """
    if nom.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(contenu), dtype=str)

    texte = _decoder(contenu)
    echantillon = "\n".join(texte.splitlines()[:5])
    try:
        separateur = csv.Sniffer().sniff(echantillon, delimiters=SEPARATEURS).delimiter
    except csv.Error:
        separateur = ","  # une seule colonne : il n'y a rien à renifler
    return pd.read_csv(io.StringIO(texte), dtype=str, sep=separateur)


def colonnes_utiles(df: pd.DataFrame) -> tuple:
    """(colonne d'adresse, colonne de type de compte). `None` si introuvable."""
    return (
        trouver_colonne(df, "adresse", "address", "localit", "lieu"),
        trouver_colonne(df, "account", "compte", "type", "profil"),
    )


def preparer(df: pd.DataFrame, col_adresse, col_compte) -> pd.DataFrame:
    """Deux colonnes uniformisées — `Adresse`, `Type de compte` — et rien d'autre.

    Toutes les autres colonnes du fichier déposé sont abandonnées ici : noms,
    téléphones et e-mails ne vont pas plus loin que la mémoire du navigateur et
    de la session.
    """
    brut = df[col_adresse] if col_adresse is not None else pd.Series(dtype=str)
    compte = (
        df[col_compte]
        if col_compte is not None
        else pd.Series([COMPTE_INCONNU] * len(df), index=df.index)
    )
    return pd.DataFrame(
        {
            "Adresse importée": brut.astype(str).str.strip(),
            "Adresse": brut.map(normaliser_adresse),
            "Type de compte": compte.map(normaliser_compte),
        }
    )


# --------------------------------------------------------------------------- #
# Correspondances retenues
# --------------------------------------------------------------------------- #


def charger_correspondances(chemin: Path | None = None) -> dict[str, str]:
    """Table `libellé importé -> libellé retenu`, indexée sur la forme repliée.

    Elle garde les fusions déjà validées : un libellé écarté une fois ne
    redemande jamais l'arbitrage, même si le fichier suivant le réintroduit.
    """
    chemin = chemin or CORRESPONDANCES
    if not chemin.exists():
        return {}
    table = pd.read_csv(chemin, dtype=str).fillna("")
    return {
        cle(ligne["Adresse importée"]): ligne["Adresse retenue"]
        for _, ligne in table.iterrows()
        if ligne["Adresse importée"] and ligne["Adresse retenue"]
    }


def enregistrer_correspondances(table: dict[str, str], chemin: Path | None = None) -> None:
    """Réécrit la table, triée : le fichier est versionné, il doit se relire."""
    chemin = chemin or CORRESPONDANCES
    chemin.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        sorted(table.items()), columns=COLONNES_CORRESPONDANCES
    ).to_csv(chemin, index=False, encoding="utf-8")


def appliquer_correspondances(adresses: pd.Series, table: dict[str, str]) -> pd.Series:
    return adresses.map(lambda a: table.get(cle(a), a))


# --------------------------------------------------------------------------- #
# Suggestions de fusion
# --------------------------------------------------------------------------- #

# Deux libellés dont la localité se ressemble à ce point sont *proposés*, jamais
# fusionnés d'office : « Itaosy » et « Itasy » passent ce seuil et désignent
# pourtant deux lieux différents. Le seuil est haut pour que la liste reste
# courte et lisible ; c'est une invitation à vérifier, pas un verdict.
SEUIL_RESSEMBLANCE = 0.88


def _localite(adresse: str) -> str:
    return cle(adresse.split(",")[0])


def _preference(adresse: str, effectifs: dict, precisions: dict) -> tuple:
    """Ordre de préférence du libellé à retenir dans un groupe.

    D'abord celui que le géocodeur a résolu exactement — c'est un point sûr sur
    la carte —, puis le plus détaillé, puis le plus représenté.
    """
    return (
        precisions.get(adresse) == "exacte",
        adresse.count(","),
        effectifs.get(adresse, 0),
    )


def suggerer_fusions(
    effectifs: dict[str, int], precisions: dict[str, str] | None = None
) -> list[dict]:
    """Groupes de libellés qui désignent peut-être le même lieu.

    Deux familles, distinguées par leur motif car elles n'ont pas la même
    fiabilité : même localité écrite avec un contexte administratif différent
    (« Mahitsy, Analamanga » et « Mahitsy, Antananarivo, Analamanga »), et
    orthographes proches (« Ambatatolampy » et « Ambatolampy »).
    """
    precisions = precisions or {}
    adresses = [a for a in effectifs if a and a != ADRESSE_INCONNUE]

    par_localite: dict[str, list[str]] = defaultdict(list)
    for adresse in adresses:
        par_localite[_localite(adresse)].append(adresse)

    groupes: list[list[str]] = []
    motifs: list[str] = []
    for libelles in par_localite.values():
        if len(libelles) > 1:
            groupes.append(libelles)
            motifs.append("même localité, contexte différent")

    # Localités proches : on ne compare que les têtes, une par groupe déjà formé,
    # et jamais deux fois la même paire.
    localites = sorted(par_localite)
    for i, gauche in enumerate(localites):
        for droite in localites[i + 1 :]:
            if abs(len(gauche) - len(droite)) > 4:
                continue
            if difflib.SequenceMatcher(None, gauche, droite).ratio() < SEUIL_RESSEMBLANCE:
                continue
            groupes.append(par_localite[gauche] + par_localite[droite])
            motifs.append("orthographes proches")

    suggestions = []
    for libelles, motif in zip(groupes, motifs):
        retenue = max(libelles, key=lambda a: _preference(a, effectifs, precisions))
        suggestions.append(
            {
                "retenue": retenue,
                "variantes": sorted(a for a in libelles if a != retenue),
                "motif": motif,
                "inscrits": sum(effectifs.get(a, 0) for a in libelles),
            }
        )
    return sorted(suggestions, key=lambda s: (-s["inscrits"], s["retenue"]))


# --------------------------------------------------------------------------- #
# Agrégat anonyme
# --------------------------------------------------------------------------- #


def agreger(df: pd.DataFrame) -> pd.DataFrame:
    """Effectifs par adresse et type de compte — le seul état conservé des lignes."""
    return (
        df.groupby(["Adresse", "Type de compte"])
        .size()
        .reset_index(name="Inscrits")
        .rename(columns={"Type de compte": "Account"})
        .sort_values(["Adresse", "Account"])
        .reset_index(drop=True)
    )


def enregistrer_agregat(agregat: pd.DataFrame, chemin: Path | None = None) -> None:
    chemin = chemin or AGREGAT
    chemin.parent.mkdir(parents=True, exist_ok=True)
    agregat.to_csv(chemin, index=False, encoding="utf-8")


def lire_agregat(chemin: Path | None = None) -> pd.DataFrame:
    chemin = chemin or AGREGAT
    if not chemin.exists():
        return pd.DataFrame(columns=["Adresse", "Account", "Inscrits"])
    return pd.read_csv(chemin, dtype=str)


# --------------------------------------------------------------------------- #
# Géocodage
# --------------------------------------------------------------------------- #

ENDPOINT = "https://nominatim.openstreetmap.org/search"
ENTETES = {"User-Agent": "carte-partenaires-eariary/1.0 (contact@esemahay.com)"}
PAUSE = 1.1  # secondes, politique d'usage de Nominatim
TENTATIVES = 3


def interroger(texte: str) -> list | None:
    """Interroge Nominatim, avec reprise : une coupure n'est pas un « rien trouvé ».

    Retourne les résultats, ou `None` si toutes les tentatives ont échoué sur une
    erreur de transport — la distinction évite d'inscrire dans le cache un
    « introuvable » qui n'est qu'un incident de connexion.
    """
    params = urllib.parse.urlencode(
        {"q": texte, "format": "json", "limit": 1, "countrycodes": "mg"}
    )
    for tentative in range(1, TENTATIVES + 1):
        try:
            requete = urllib.request.Request(f"{ENDPOINT}?{params}", headers=ENTETES)
            with urllib.request.urlopen(requete, timeout=30) as reponse:
                return json.load(reponse)
        except Exception:
            time.sleep(PAUSE * 2 * tentative)
    return None


def geocoder(adresse: str, requete=interroger, pause: float = PAUSE) -> dict:
    """Essaie l'adresse complète puis, en cas d'échec, des variantes plus larges.

    « Anosibe, Antananarivo, Analamanga » devient successivement
    « Antananarivo, Analamanga » puis « Analamanga » : on perd en précision mais
    on garde le point sur la bonne zone.
    """
    parties = [p.strip() for p in str(adresse).split(",") if p.strip()]
    # Une adresse sans contexte administratif (« Paris », « G 149 ») ne peut pas
    # être vérifiée : la recherche restreinte à Madagascar renvoie toujours
    # quelque chose, sans rien garantir. Le résultat est gardé, dit « incertaine ».
    structuree = len(parties) > 1
    if structuree and cle(parties[-1]) in PAYS:
        parties = parties[:-1]  # interroger « Madagascar » seul n'apprend rien

    incident = False
    for depart in range(len(parties)):
        candidate = ", ".join(parties[depart:]) + ", Madagascar"
        trouves = requete(candidate)
        if pause:
            time.sleep(pause)
        if trouves is None:
            incident = True
            continue
        if trouves:
            if not structuree:
                precision = "incertaine"
            else:
                precision = "exacte" if depart == 0 else "approchée"
            return {
                "lat": float(trouves[0]["lat"]),
                "lon": float(trouves[0]["lon"]),
                "precision": precision,
                "correspondance": trouves[0].get("display_name", ""),
            }

    return {
        "lat": "",
        "lon": "",
        "precision": "erreur réseau" if incident else "introuvable",
        "correspondance": "",
    }


def charger_cache_geo(chemin: Path | None = None) -> dict[str, dict]:
    chemin = chemin or CACHE_GEO
    if not chemin.exists():
        return {}
    table = pd.read_csv(chemin, dtype=str).fillna("")
    return {ligne["Adresse"]: dict(ligne) for _, ligne in table.iterrows()}


def enregistrer_cache_geo(cache: dict[str, dict], chemin: Path | None = None) -> None:
    chemin = chemin or CACHE_GEO
    chemin.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [{colonne: cache[adresse].get(colonne, "") for colonne in COLONNES_CACHE}
         for adresse in sorted(cache)],
        columns=COLONNES_CACHE,
    ).to_csv(chemin, index=False, encoding="utf-8")


def adresses_a_geocoder(adresses, cache: dict[str, dict]) -> list[str]:
    """Adresses jamais résolues, dans l'ordre alphabétique.

    Une adresse déjà dans le cache n'est pas réinterrogée, même approchée : c'est
    ce qui rend un second import quasi instantané. `--retry` du script hors ligne
    reste le moyen de reprendre les résolutions douteuses.
    """
    connues = set(cache)
    return sorted(
        {
            adresse
            for adresse in adresses
            if adresse and adresse != ADRESSE_INCONNUE and adresse not in connues
        }
    )


# --------------------------------------------------------------------------- #
# Comparaison avant / après
# --------------------------------------------------------------------------- #


def resume_uniformisation(df: pd.DataFrame) -> pd.DataFrame:
    """Libellés que l'uniformisation a modifiés, avec leur effectif.

    Le rapport que l'interface montre avant d'écrire quoi que ce soit : c'est là
    qu'une règle trop zélée se voit.
    """
    change = df[df["Adresse importée"].str.strip() != df["Adresse"]]
    if change.empty:
        return pd.DataFrame(columns=["Adresse importée", "Adresse retenue", "Lignes"])
    return (
        change.groupby(["Adresse importée", "Adresse"])
        .size()
        .reset_index(name="Lignes")
        .rename(columns={"Adresse": "Adresse retenue"})
        .sort_values(["Lignes", "Adresse retenue"], ascending=[False, True])
        .reset_index(drop=True)
    )


def effectifs_par_adresse(df: pd.DataFrame) -> dict[str, int]:
    return Counter(df["Adresse"])
