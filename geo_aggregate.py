"""
Moteur d'agrégation spatiale — carte des partenaires eAriary.

Rattache les pré-souscripteurs géocodés et les établissements partenaires aux
découpages administratifs de Madagascar (Région / District / Commune), puis
agrège les effectifs par zone pour l'affichage choroplèthe.

Deux règles structurent le rattachement :

* un point contenu dans un polygone lui est rattaché (`within`) ;
* un point qui ne tombe dans aucun polygone — imprécision du géocodage,
  arrondi du littoral, îlot absent du découpage — est rattaché au polygone le
  plus proche et marqué `rattachement_approx`. La proximité est calculée en
  EPSG:32738 (UTM 38S, adapté à Madagascar) : en coordonnées géographiques les
  distances de `sjoin_nearest` seraient exprimées en degrés, donc fausses.

Les géométries proviennent de `data/geo/mdg_adm{1,2,3}.geojson`, produits par
`tools/fetch_boundaries.py`. Chaque Feature porte `code_zone`, `nom_zone`,
`niveau`, `code_parent`, `nom_parent`.

La logique est isolée dans des fonctions privées non décorées
(`_charger_zones`, `_agreger`) : les tests unitaires les appellent avec des
polygones synthétiques, sans runtime Streamlit ni fichier sur disque.
"""

from __future__ import annotations

import html
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------- #
# Référentiels et constantes
# --------------------------------------------------------------------------- #

# Libellé affiché -> suffixe du fichier GeoJSON.
NIVEAUX = {"Région": "adm1", "District": "adm2", "Commune": "adm3"}

# Catégories d'établissements suivies, dans l'ordre des colonnes `etab_*`.
CATEGORIES = ["Boutique", "Épicerie", "Hôtel", "Magasin", "Restaurant", "Supermarché"]

BASE_DIR = Path(__file__).resolve().parent
GEO_DIR = BASE_DIR / "data" / "geo"

CRS_WGS84 = "EPSG:4326"
# UTM 38S : couvre Madagascar en entier, distances métriques fiables.
CRS_METRIQUE = "EPSG:32738"

# Propriétés attendues sur chaque Feature des GeoJSON.
COLONNES_ZONE = ["code_zone", "nom_zone", "niveau", "code_parent", "nom_parent"]

# Colonnes du GeoDataFrame retourné, dans cet ordre exact.
COLONNES_SORTIE = (
    COLONNES_ZONE
    + ["inscrits", "localites", "etablissements"]
    + [f"etab_{c}" for c in CATEGORIES]
    + [
        "ratio_inscrits_etab",
        "part_pct",
        "rattachement_approx_n",
        "localites_detail",
        "etablissements_detail",
        "geometry",
    ]
)

# Colonnes du DataFrame de détail, dans cet ordre exact.
COLONNES_DETAIL = [
    "code_zone",
    "nom_zone",
    "niveau",
    "Localité",
    "Ville",
    "Région",
    "inscrits",
    "rattachement_approx",
]

# Nombre de localités listées dans le popup avant le résumé « et N autres ».
MAX_LOCALITES_DETAIL = 6

# Même libellé que `app.py` pour une valeur textuelle absente.
NON_RENSEIGNE = "Non renseignée"


# --------------------------------------------------------------------------- #
# Accès aux fichiers de géométries
# --------------------------------------------------------------------------- #


def chemin_zones(niveau: str) -> Path:
    """Chemin du GeoJSON d'un niveau. Accepte « Commune » ou « adm3 »."""
    code = NIVEAUX.get(niveau, niveau)
    if code not in set(NIVEAUX.values()):
        attendus = ", ".join(NIVEAUX)
        raise ValueError(f"Niveau inconnu : {niveau!r} (attendu : {attendus})")
    return GEO_DIR / f"mdg_{code}.geojson"


def zones_disponibles() -> bool:
    """True si les trois GeoJSON attendus sont présents et lisibles.

    Contrôle volontairement léger (existence, taille non nulle, premier octet
    d'un objet JSON) : ouvrir réellement les trois couches coûterait plusieurs
    secondes au démarrage alors que l'appelant ne cherche qu'à savoir s'il peut
    proposer la vue par zone.
    """
    for niveau in NIVEAUX:
        try:
            chemin = chemin_zones(niveau)
            if not chemin.is_file() or chemin.stat().st_size == 0:
                return False
            with chemin.open("rb") as flux:
                if flux.read(1) not in (b"{", b"\xef"):  # objet JSON ou BOM UTF-8
                    return False
        except OSError:
            return False
    return True


def _normaliser_zones(zones: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Vérifie les propriétés attendues et harmonise types et CRS.

    Ne modifie pas l'objet reçu. `code_parent` / `nom_parent` sont ramenés à
    `None` plutôt qu'à `NaN` : le niveau Région n'a pas de parent et un `NaN`
    remonterait tel quel dans les popups.
    """
    if not isinstance(zones, gpd.GeoDataFrame):
        raise TypeError("`zones` doit être un GeoDataFrame")
    manquantes = [c for c in COLONNES_ZONE if c not in zones.columns]
    if manquantes:
        raise ValueError(f"Propriétés absentes des zones : {', '.join(manquantes)}")

    out = zones.copy()
    if out.crs is None:
        out = out.set_crs(CRS_WGS84)
    elif out.crs.to_string() != CRS_WGS84:
        out = out.to_crs(CRS_WGS84)

    for colonne in ("code_zone", "nom_zone", "niveau"):
        out[colonne] = out[colonne].astype("string").fillna("").astype(object)
    for colonne in ("code_parent", "nom_parent"):
        serie = out[colonne].astype(object)
        out[colonne] = serie.where(serie.notna(), None)

    out = out[COLONNES_ZONE + ["geometry"]]
    return gpd.GeoDataFrame(out, geometry="geometry", crs=CRS_WGS84).reset_index(
        drop=True
    )


def _charger_zones(chemin: Path | str) -> gpd.GeoDataFrame:
    """Lit un GeoJSON de zones et le normalise (fonction pure, testable)."""
    chemin = Path(chemin)
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Géométries absentes : {chemin}. Lancez "
            "`python tools/fetch_boundaries.py` pour les télécharger."
        )
    return _normaliser_zones(gpd.read_file(chemin))


# Le cache porte sur (chemin, mtime) et non sur le seul niveau : sans la date de
# modification, un rafraîchissement des géométries par `tools/fetch_boundaries.py`
# ne serait jamais vu dans la session en cours.
#
# Attention : Streamlit EXCLUT du hachage tout paramètre dont le nom commence par
# « _ ». `mtime` doit donc rester sans préfixe pour entrer dans la clé de cache.
@st.cache_data(show_spinner=False)
def _charger_zones_cache(chemin: str, mtime: float) -> gpd.GeoDataFrame:
    return _charger_zones(chemin)


def load_zones(niveau: str) -> gpd.GeoDataFrame:
    """Lit `data/geo/mdg_<niveau>.geojson`. Lève FileNotFoundError si absent.

    Résultat mis en cache sur (fichier, date de modification, niveau).
    """
    chemin = chemin_zones(niveau)
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Géométries absentes pour le niveau « {niveau} » : {chemin}. "
            "Lancez `python tools/fetch_boundaries.py` pour les télécharger."
        )
    return _charger_zones_cache(str(chemin), chemin.stat().st_mtime)


# --------------------------------------------------------------------------- #
# Rattachement des points aux polygones
# --------------------------------------------------------------------------- #


def _points(source: pd.DataFrame, colonnes: list[str]) -> gpd.GeoDataFrame:
    """Convertit un DataFrame `lat`/`lon` en points EPSG:4326.

    Les lignes sans coordonnées exploitables sont ignorées silencieusement.
    La source n'est jamais modifiée en place.
    """
    vide = gpd.GeoDataFrame(
        {c: pd.Series(dtype=object) for c in colonnes},
        geometry=gpd.GeoSeries([], crs=CRS_WGS84),
        crs=CRS_WGS84,
    )
    if source is None or len(source) == 0:
        return vide
    if "lat" not in source.columns or "lon" not in source.columns:
        return vide

    lat = pd.to_numeric(source["lat"], errors="coerce")
    lon = pd.to_numeric(source["lon"], errors="coerce")
    garde = (lat.notna() & lon.notna()).to_numpy()
    if not garde.any():
        return vide

    attributs = {}
    for colonne in colonnes:
        if colonne in source.columns:
            valeurs = source[colonne].to_numpy(dtype=object)[garde]
        else:
            valeurs = np.full(int(garde.sum()), NON_RENSEIGNE, dtype=object)
        attributs[colonne] = valeurs

    geometrie = gpd.points_from_xy(lon.to_numpy()[garde], lat.to_numpy()[garde])
    return gpd.GeoDataFrame(attributs, geometry=geometrie, crs=CRS_WGS84).reset_index(
        drop=True
    )


def _rattacher(
    points: gpd.GeoDataFrame, zones: gpd.GeoDataFrame
) -> tuple[np.ndarray, np.ndarray]:
    """Associe chaque point à une zone.

    Retourne (indices positionnels de zone, drapeaux d'approximation). Un
    indice à -1 signale qu'aucune zone n'a pu être trouvée (liste de zones
    vide) ; le drapeau est True quand le rattachement s'est fait par proximité
    et non par contenance.
    """
    nb = len(points)
    indices = np.full(nb, -1, dtype=np.int64)
    approx = np.zeros(nb, dtype=bool)
    if nb == 0 or len(zones) == 0:
        return indices, approx

    zg = zones[["geometry"]].copy()
    zg["_zi"] = np.arange(len(zg), dtype=np.int64)
    pg = points[["geometry"]].copy()
    pg["_pi"] = np.arange(nb, dtype=np.int64)

    # Contenance stricte. Un point posé sur une frontière commune peut ressortir
    # deux fois : la première zone rencontrée l'emporte, arbitrairement mais de
    # façon reproductible (ordre des polygones dans le fichier).
    dedans = gpd.sjoin(pg, zg, predicate="within", how="inner")
    if len(dedans):
        dedans = dedans[~dedans["_pi"].duplicated()]
        indices[dedans["_pi"].to_numpy()] = dedans["_zi"].to_numpy()

    reste = indices < 0
    if reste.any():
        # Reprojection métrique obligatoire : `sjoin_nearest` en EPSG:4326
        # mesurerait des degrés (et geopandas émettrait un UserWarning).
        pm = pg.loc[reste].to_crs(CRS_METRIQUE)
        zm = zg.to_crs(CRS_METRIQUE)
        proches = gpd.sjoin_nearest(pm, zm, how="inner")
        if len(proches):
            proches = proches[~proches["_pi"].duplicated()]
            cibles = proches["_pi"].to_numpy()
            indices[cibles] = proches["_zi"].to_numpy()
            approx[cibles] = True

    return indices, approx


# --------------------------------------------------------------------------- #
# Agrégation
# --------------------------------------------------------------------------- #


def _texte(valeur) -> str:
    """Normalise une valeur textuelle : NaN, vide et « nan » -> Non renseignée."""
    if valeur is None or (isinstance(valeur, float) and np.isnan(valeur)):
        return NON_RENSEIGNE
    texte = str(valeur).strip()
    if not texte or texte.lower() in {"nan", "none", "<na>"}:
        return NON_RENSEIGNE
    return texte


def _serie_texte(serie: pd.Series) -> pd.Series:
    return serie.map(_texte)


def _rang_information(colonnes: list[pd.Series]) -> np.ndarray:
    """Nombre de valeurs manquantes d'une ligne, pour trier du plus au moins sûr.

    Trier les points sur ce rang avant le regroupement permet de retenir la
    Ville / Région la plus informative d'une localité avec le simple `first`
    (vectorisé), au lieu d'une fonction Python appelée groupe par groupe —
    coûteuse sur les colonnes texte de pandas 3.
    """
    rang = np.zeros(len(colonnes[0]), dtype=np.int16)
    for colonne in colonnes:
        rang += (colonne.to_numpy(dtype=object) == NON_RENSEIGNE).astype(np.int16)
    return rang


def _parts_pct(inscrits: np.ndarray) -> np.ndarray:
    """Part en % du total national, arrondie à 2 décimales, de somme exacte.

    Arrondir chaque part indépendamment ferait dériver la somme de plusieurs
    points au niveau Commune (~1600 zones). La méthode du plus fort reste
    répartit les centièmes manquants sur les zones aux plus grandes décimales
    tronquées, ce qui garantit un total de 100,00 %.
    """
    total = int(inscrits.sum())
    parts = np.zeros(len(inscrits), dtype=float)
    if total <= 0:
        return parts

    exact = inscrits.astype(float) * 10000.0 / total  # en centièmes de %
    base = np.floor(exact).astype(np.int64)
    manquants = 10000 - int(base.sum())
    if manquants > 0:
        # Seules les zones ayant au moins un inscrit peuvent recevoir un
        # centième : une zone vide doit rester à 0,00 %.
        candidats = np.argsort(-(exact - base), kind="stable")
        candidats = [i for i in candidats if inscrits[i] > 0][:manquants]
        base[candidats] += 1
    return base / 100.0


def _detail_localites(noms: list[str], effectifs: list[int]) -> str:
    """« Anosibe (55) · Itaosy (22) · … · et 3 autres », prêt pour un popup HTML."""
    if not noms:
        return ""
    morceaux = [
        f"{html.escape(nom)} ({int(n)})"
        for nom, n in zip(noms[:MAX_LOCALITES_DETAIL], effectifs[:MAX_LOCALITES_DETAIL])
    ]
    surplus = len(noms) - MAX_LOCALITES_DETAIL
    if surplus > 0:
        morceaux.append(f"et {surplus} autre{'s' if surplus > 1 else ''}")
    return " · ".join(morceaux)


def _rang_categorie(categorie: str) -> tuple[int, str]:
    """Ordre de départage : référentiel, puis hors référentiel, « Non
    renseignée » en dernier."""
    if categorie in CATEGORIES:
        return (CATEGORIES.index(categorie), "")
    if categorie == NON_RENSEIGNE:
        return (len(CATEGORIES) + 1, "")
    return (len(CATEGORIES), categorie)


def _detail_etablissements(compte: dict[str, int]) -> str:
    """« Restaurant 3 · Hôtel 1 » — catégories non nulles, effectif décroissant."""
    presentes = [(c, int(n)) for c, n in compte.items() if int(n) > 0]
    presentes.sort(key=lambda item: (-item[1], _rang_categorie(item[0])))
    return " · ".join(f"{html.escape(c)} {n}" for c, n in presentes)


def _detail_vide() -> pd.DataFrame:
    """Squelette typé du DataFrame de détail (aucun point géolocalisé)."""
    return pd.DataFrame(
        {
            "code_zone": pd.Series(dtype=object),
            "nom_zone": pd.Series(dtype=object),
            "niveau": pd.Series(dtype=object),
            "Localité": pd.Series(dtype=object),
            "Ville": pd.Series(dtype=object),
            "Région": pd.Series(dtype=object),
            "inscrits": pd.Series(dtype="int64"),
            "rattachement_approx": pd.Series(dtype=bool),
        }
    )


def _agreger(
    souscripteurs: pd.DataFrame,
    etablissements: pd.DataFrame,
    zones: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Jointure spatiale + agrégation par zone (fonction pure, testable).

    `zones` est la couche administrative du niveau visé ; toutes ses zones sont
    présentes en sortie, y compris celles sans aucun point.
    """
    zones = _normaliser_zones(zones)
    nb_zones = len(zones)

    pts_sous = _points(souscripteurs, ["Localité", "Ville", "Région"])
    pts_etab = _points(etablissements, ["Catégorie"])
    zi_sous, approx_sous = _rattacher(pts_sous, zones)
    zi_etab, _ = _rattacher(pts_etab, zones)

    # --- Pré-souscripteurs : détail par zone × localité ---------------------
    rattaches = pd.DataFrame(
        {
            "_zi": zi_sous,
            "Localité": _serie_texte(pts_sous["Localité"]),
            "Ville": _serie_texte(pts_sous["Ville"]),
            "Région": _serie_texte(pts_sous["Région"]),
            "approx": approx_sous,
        }
    )
    rattaches = rattaches[rattaches["_zi"] >= 0]

    if len(rattaches):
        ordonne = rattaches.assign(
            _info=_rang_information([rattaches["Ville"], rattaches["Région"]])
        ).sort_values("_info", kind="mergesort")
        par_localite = (
            ordonne.groupby(["_zi", "Localité"], sort=False)
            .agg(
                inscrits=("approx", "size"),
                rattachement_approx=("approx", "any"),
                Ville=("Ville", "first"),
                Région=("Région", "first"),
            )
            .reset_index()
        )
    else:
        par_localite = pd.DataFrame(
            {
                "_zi": pd.Series(dtype="int64"),
                "Localité": pd.Series(dtype=object),
                "inscrits": pd.Series(dtype="int64"),
                "rattachement_approx": pd.Series(dtype=bool),
                "Ville": pd.Series(dtype=object),
                "Région": pd.Series(dtype=object),
            }
        )

    # Tri unique, réutilisé pour le détail et pour les libellés de popup :
    # effectif décroissant, puis alphabétique pour rester déterministe.
    par_localite = par_localite.sort_values(
        ["_zi", "inscrits", "Localité"], ascending=[True, False, True], kind="mergesort"
    )

    inscrits = np.zeros(nb_zones, dtype=np.int64)
    localites = np.zeros(nb_zones, dtype=np.int64)
    approx_n = np.zeros(nb_zones, dtype=np.int64)
    localites_detail = np.full(nb_zones, "", dtype=object)

    if len(par_localite):
        zi_loc = par_localite["_zi"].to_numpy(dtype=np.int64)
        noms_loc = par_localite["Localité"].to_numpy(dtype=object)
        eff_loc = par_localite["inscrits"].to_numpy(dtype=np.int64)

        inscrits = np.bincount(zi_loc, weights=eff_loc, minlength=nb_zones).astype(
            np.int64
        )
        localites = np.bincount(zi_loc, minlength=nb_zones).astype(np.int64)
        approx_n = np.bincount(
            rattaches["_zi"].to_numpy(dtype=np.int64),
            weights=rattaches["approx"].to_numpy(dtype=float),
            minlength=nb_zones,
        ).astype(np.int64)

        # `par_localite` est trié par zone : les bornes de chaque zone se lisent
        # par recherche dichotomique, ce qui évite d'itérer sur un groupby
        # pandas (découpage de DataFrame à chaque groupe).
        rangs = np.arange(nb_zones)
        debuts = np.searchsorted(zi_loc, rangs, side="left")
        fins = np.searchsorted(zi_loc, rangs, side="right")
        for zi in np.nonzero(fins > debuts)[0]:
            tranche = slice(debuts[zi], fins[zi])
            localites_detail[zi] = _detail_localites(
                noms_loc[tranche].tolist(), eff_loc[tranche].tolist()
            )

    # --- Établissements : total et ventilation par catégorie ----------------
    etab_rattaches = pd.DataFrame(
        {"_zi": zi_etab, "Catégorie": _serie_texte(pts_etab["Catégorie"])}
    )
    etab_rattaches = etab_rattaches[etab_rattaches["_zi"] >= 0]

    etablissements_n = np.zeros(nb_zones, dtype=np.int64)
    par_categorie = {
        categorie: np.zeros(nb_zones, dtype=np.int64) for categorie in CATEGORIES
    }
    etab_detail = np.full(nb_zones, "", dtype=object)

    if len(etab_rattaches):
        totaux = etab_rattaches.groupby("_zi").size()
        etablissements_n[totaux.index.to_numpy().astype(int)] = (
            totaux.to_numpy().astype(np.int64)
        )
        croise = (
            etab_rattaches.groupby(["_zi", "Catégorie"]).size().unstack(fill_value=0)
        )
        lignes = croise.index.to_numpy().astype(int)
        for categorie in croise.columns:
            valeurs = croise[categorie].to_numpy().astype(np.int64)
            if categorie in par_categorie:
                par_categorie[categorie][lignes] = valeurs
        # Le détail affiche aussi les catégories hors référentiel (« Non
        # renseignée ») pour que la somme corresponde au total de la zone.
        for zi, ligne in zip(lignes, croise.to_dict(orient="records")):
            etab_detail[zi] = _detail_etablissements(ligne)

    # --- Ratios et parts ---------------------------------------------------
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = np.where(
            etablissements_n > 0,
            np.round(inscrits / np.where(etablissements_n > 0, etablissements_n, 1), 2),
            np.nan,
        )
    # Colonne objet : `None` (et non `NaN`) quand la zone n'a aucun partenaire,
    # jamais `inf`.
    ratio_colonne = np.array(
        [None if not np.isfinite(r) else float(r) for r in ratios], dtype=object
    )

    # --- Assemblage --------------------------------------------------------
    sortie = zones[COLONNES_ZONE].copy()
    sortie["inscrits"] = inscrits
    sortie["localites"] = localites
    sortie["etablissements"] = etablissements_n
    for categorie in CATEGORIES:
        sortie[f"etab_{categorie}"] = par_categorie[categorie]
    sortie["ratio_inscrits_etab"] = ratio_colonne
    sortie["part_pct"] = _parts_pct(inscrits)
    sortie["rattachement_approx_n"] = approx_n
    sortie["localites_detail"] = localites_detail
    sortie["etablissements_detail"] = etab_detail
    sortie["geometry"] = zones.geometry.to_numpy()

    zones_sortie = gpd.GeoDataFrame(
        sortie[COLONNES_SORTIE], geometry="geometry", crs=CRS_WGS84
    )

    # --- Détail zone × localité -------------------------------------------
    if len(par_localite):
        reference = zones[["code_zone", "nom_zone", "niveau"]].copy()
        reference["_zi"] = np.arange(nb_zones, dtype=np.int64)
        detail = par_localite.merge(reference, on="_zi", how="left")
        detail = detail[COLONNES_DETAIL].sort_values(
            ["code_zone", "inscrits", "Localité"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        detail["inscrits"] = detail["inscrits"].astype("int64")
        detail["rattachement_approx"] = detail["rattachement_approx"].astype(bool)
        detail = detail.reset_index(drop=True)
    else:
        detail = _detail_vide()

    return zones_sortie, detail


# Comme pour les zones, la date de modification du GeoJSON entre dans la clé :
# les DataFrames d'entrée sont hachables par Streamlit, le fichier sur disque non.
@st.cache_data(show_spinner=False)
def _agreger_cache(
    souscripteurs: pd.DataFrame,
    etablissements: pd.DataFrame,
    niveau: str,
    mtime: float,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    return _agreger(souscripteurs, etablissements, load_zones(niveau))


def aggregate(
    souscripteurs: pd.DataFrame, etablissements: pd.DataFrame, niveau: str
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Jointure spatiale + agrégation. Retourne (zones, detail).

    `zones` : un enregistrement par zone du niveau (y compris les zones sans
    aucun inscrit), en EPSG:4326. `detail` : un enregistrement par couple
    zone × localité. Les lignes d'entrée sans `lat`/`lon` sont ignorées.
    """
    chemin = chemin_zones(niveau)
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Géométries absentes pour le niveau « {niveau} » : {chemin}. "
            "Lancez `python tools/fetch_boundaries.py` pour les télécharger."
        )
    zones, detail = _agreger_cache(
        souscripteurs, etablissements, niveau, chemin.stat().st_mtime
    )
    # Copies défensives : l'appelant peut trier ou filtrer sans polluer le cache.
    return zones.copy(), detail.copy()
