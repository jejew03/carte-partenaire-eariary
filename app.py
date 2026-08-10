"""
Carte des établissements — Madagascar
Lit les données depuis un Google Sheet public (export CSV) avec repli
sur une copie locale embarquée si le réseau ou le partage n'est pas disponible.

Superpose les pré-souscripteurs eAriary (fichier Excel local), agrégés par
localité : le fichier ne contient que des adresses textuelles, géocodées une
fois pour toutes par `tools/geocode_souscripteurs.py`.

Ces inscrits sont restitués en choroplèthe de zones administratives (région,
district ou commune) via `geo_aggregate`, les établissements partenaires
restant des marqueurs ponctuels par-dessus les polygones. Sans les contours
`data/geo/mdg_adm*.geojson`, l'application retombe sur des cercles
proportionnels par localité.

Lancement :  streamlit run app.py
"""

import html
import io
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# Import des pré-inscrits : lecture du fichier déposé, uniformisation des
# adresses, agrégation et géocodage. Les règles ne vivent que là.
import pre_inscrits

# Agrégation géographique : produite par `tools/fetch_boundaries.py` +
# `geo_aggregate.py`. Absente d'un dépôt fraîchement cloné, d'où l'import
# tolérant — l'application doit rester utilisable sans choroplèthe.
try:
    import geo_aggregate
except Exception:  # ImportError, mais aussi geopandas absent ou cassé
    geo_aggregate = None

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

SHEET_ID = "1D15egjrBB_9eNCXC-THxZcSqvNtf7ttfssdcVDRu8Yo"
GID = "0"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"

# Pages publiques à intégrer, publiées par GitHub Pages depuis `partenaires/`.
# La vue « Intégration » s'en sert pour les liens, le code à copier et l'aperçu.
PAGES_PUBLIQUES = "https://jejew03.github.io/carte-partenaire-eariary/partenaires"

# Chaque catégorie : (couleur du marqueur Folium, icône Font Awesome 6, teinte
# exacte du marqueur). La teinte sert à la légende, pour qu'elle corresponde
# visuellement aux marqueurs de leaflet-awesome-markers.
CATEGORY_STYLE = {
    "Restaurant": ("red", "utensils", "#D63E2A"),
    "Hôtel": ("darkblue", "bed", "#0067A3"),
    "Boutique": ("green", "bag-shopping", "#72B026"),
    "Épicerie": ("orange", "basket-shopping", "#F69730"),
    "Magasin": ("purple", "store", "#D252B9"),
    "Supermarché": ("cadetblue", "cart-shopping", "#436978"),
}
DEFAULT_STYLE = ("gray", "location-dot", "#575757")

# Pré-souscripteurs eAriary : fichier local + cache de géocodage des adresses.
BASE_DIR = Path(__file__).resolve().parent
SUBSCRIBERS_XLSX = BASE_DIR / "Stat_Inscription_eAr_10072026_final.xlsx"
GEOCODE_CACHE = BASE_DIR / "data" / "adresses_geocodees.csv"
SUBSCRIBERS_AGGREGATE = BASE_DIR / "data" / "pre_souscripteurs_agreges.csv"

# Un seul ton pour la couche pré-souscripteurs : c'est la taille du cercle qui
# porte l'information (nombre d'inscrits), pas la couleur.
SUBSCRIBER_COLOR = "#4F46E5"
# Référentiel unique, partagé avec l'import : deux listes de types de compte qui
# divergeraient feraient apparaître des colonnes fantômes dans le récapitulatif.
ACCOUNT_ORDER = pre_inscrits.COMPTES

# ------------------------- Choroplèthe par zone ---------------------------- #
# Rampe séquentielle bleue, alignée sur la couleur primaire du thème. Une
# entrée par nombre de classes réellement obtenu : les quantiles se
# dédoublonnent souvent (beaucoup de zones à faible effectif), et une rampe de
# 5 tons ramenée à 2 classes donnerait deux bleus indiscernables.
ZONE_RAMPS = {
    1: ["#5B90E0"],
    2: ["#A8C6EF", "#1E4FA8"],
    3: ["#C7DBF7", "#5B90E0", "#173A80"],
    4: ["#C7DBF7", "#8FB8EE", "#3468C4", "#173A80"],
    5: ["#C7DBF7", "#8FB8EE", "#5B90E0", "#2E63C0", "#173A80"],
}
ZONE_CLASSES = 5

# Le zéro n'est pas « la plus petite valeur » : il reçoit son propre gris, un
# contour tireté et un remplissage plus transparent, pour rester lisible même
# pour un œil qui ne distingue pas les bleus clairs.
ZONE_ZERO_FILL = "#F1F4F8"
ZONE_ZERO_STROKE = "#94A3B8"
# Densité non calculable : des inscrits mais aucun établissement de référence.
ZONE_NA_FILL = "#DCE2EA"

# Métrique de coloriage : libellé -> (colonne, décimales, unité, aide).
ZONE_METRICS = {
    "Valeur absolue — inscrits": (
        "inscrits",
        0,
        "inscrit(s)",
        "Nombre de pré-souscripteurs rattachés à la zone.",
    ),
    "Densité — inscrits par établissement": (
        "ratio_inscrits_etab",
        2,
        "inscrit(s) / établissement",
        "Inscrits divisés par le nombre d'établissements partenaires de la zone. "
        "Non calculable sans établissement.",
    ),
    "Part du total (%)": (
        "part_pct",
        2,
        "% du total",
        "Poids de la zone dans le total des inscrits localisés.",
    ),
}

# Le champ « Adresse » du fichier d'inscription contient parfois une adresse
# e-mail : sans valeur géographique, et affichée telle quelle elle identifierait
# une personne. Règle définie dans `pre_inscrits`, d'où vient aussi l'import.
EMAIL_LIKE = pre_inscrits.EMAIL_LIKE
UNKNOWN_ADDRESS = pre_inscrits.ADRESSE_INCONNUE

# Font Awesome 6 ne rattache la police qu'aux classes .fas / .fa-solid, alors que
# leaflet-awesome-markers n'émet que .fa : sans ce correctif les marqueurs
# affichent un carré vide à la place de l'icône.
MAP_ICON_FIX = """
<style>
  .awesome-marker i.fa { font-family: "Font Awesome 6 Free"; font-weight: 900; }
</style>
"""

# Styles des popups de zone, injectés une seule fois dans l'en-tête de la carte.
# Le niveau Commune compte ~1600 polygones : répéter des attributs `style` dans
# chaque popup alourdirait le GeoJSON de plus d'un mégaoctet.
MAP_ZONE_CSS = """
<style>
  .zpop { font-family: Inter, system-ui, sans-serif; min-width: 210px; color: #0F172A; }
  .zpop b { font-weight: 600; }
  .zpop-h { font-size: 14px; font-weight: 600; line-height: 1.35; }
  .zpop-s { font-size: 12px; color: #475569; margin-top: 2px; }
  .zpop-n { display: inline-flex; align-items: center; gap: 6px; margin: 8px 0 6px;
            padding: 2px 8px; border-radius: 999px; background: #EEF2FF;
            font-size: 11px; color: #3730A3; font-weight: 500; }
  .zpop-n::before { content: ""; width: 7px; height: 7px; border-radius: 50%;
                    background: #4F46E5; }
  .zpop-r { font-size: 12px; color: #334155; margin-top: 4px; }
  .zpop-d { font-size: 12px; color: #475569; margin-top: 4px; }
  .zpop-a { font-size: 11px; color: #92400E; background: #FEF3C7;
            border-radius: 6px; padding: 4px 8px; margin-top: 6px; }
</style>
"""

# Copie de secours des données (au cas où le Sheet ne serait pas public)
FALLBACK_CSV = """Province,Nom de l'établissement,Catégorie,Latitude / longitude
Antsiranana,Tabet Shop,Supermarché,"-12.289942563129966, 49.291381037077876"
Fianarantsoa,Chez Domm,Restaurant,"-21.44842549288241, 47.086873267404826"
Fianarantsoa,BABI FOOD,Restaurant,"-21.44172567228877, 47.09298049252991"
Mahajanga,Housseni Store (« le coin des épices et des saveurs »),Épicerie,"-15.722778283458634, 46.31315196117407"
Mahajanga,Chez Tranquille,Hôtel,"-15.718495604915958, 46.304429388697784"
Mahajanga,Restaurant La Terrasse,Restaurant,"-15.724088665530097, 46.30951194135671"
Tolagnaro,Le port hôtel,Hôtel,"-25.025445492915278, 46.99056656722333"
Tolagnaro,Chez Rosii,Restaurant,"-25.022228695380868, 46.98532819768194"
Tolagnaro,Sucré salé Shop,Boutique,"-25.03559939919153, 46.99496525966426"
Tolagnaro,Sucré salé,Restaurant,"-25.03559939919153, 46.99496525966426"
Tolagnaro,B Boutique mdg,Boutique,"-25.022354544265976, 46.98536221066723"
Tolagnaro,Boutique Annia Tine,Boutique,"Introuvable, quartier Amparihy"
Toamasina,Restaurant la Paillotte,Restaurant,"-18.158589676212383, 49.41215244822356"
Sambava,Le Pavé Sambavienne,Restaurant,"-14.265439924119013, 50.169405201559925"
Sambava,Magasin Fakhri,Magasin,"-14.254504508559359, 50.15725603831986"
Sambava,IDENTIC . MG (lodge Antsiraka),Hôtel,"-14.310942496886263, 50.190299511340505"
"""

# --------------------------------------------------------------------------- #
# Chargement & nettoyage
# --------------------------------------------------------------------------- #

COORD_RE = re.compile(
    r"^\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*[,;]\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*$"
)


def parse_coords(value):
    """Extrait (lat, lon) d'une cellule texte. Retourne (None, None) si illisible."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, None
    text = str(value).replace("\\", "").strip()
    match = COORD_RE.match(text)
    if not match:
        return None, None
    lat = float(match.group(1).replace(",", "."))
    lon = float(match.group(2).replace(",", "."))
    # Garde-fou : coordonnées plausibles pour Madagascar (large marge)
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None, None
    return lat, lon


def normalize_header(raw: pd.DataFrame) -> pd.DataFrame:
    """Trouve la vraie ligne d'en-tête (celle contenant 'Province') et l'applique."""
    header_row = 0
    for idx in range(min(len(raw), 10)):
        row_text = " ".join(str(v) for v in raw.iloc[idx].tolist()).lower()
        if "province" in row_text:
            header_row = idx
            break
    df = raw.iloc[header_row + 1 :].copy()
    df.columns = [str(c).strip() for c in raw.iloc[header_row].tolist()]
    return df


def sort_fr(values):
    """Tri alphabétique insensible aux accents : « Épicerie » suit « Boutique »."""
    def key(value):
        text = unicodedata.normalize("NFKD", str(value))
        return "".join(c for c in text if not unicodedata.combining(c)).lower()

    return sorted(values, key=key)


def find_col(df, *keywords):
    """Retourne le nom de la première colonne dont l'intitulé contient un mot-clé."""
    for col in df.columns:
        low = str(col).lower()
        if any(k in low for k in keywords):
            return col
    return None


@st.cache_data(ttl=300, show_spinner=False)
def load_data():
    """Charge le Google Sheet ; repli sur les données embarquées en cas d'échec."""
    source = "Google Sheet (en direct)"
    try:
        raw = pd.read_csv(CSV_URL, header=None, dtype=str)
        if raw.empty:
            raise ValueError("feuille vide")
    except Exception:
        source = "Copie locale de secours"
        raw = pd.read_csv(io.StringIO(FALLBACK_CSV), header=None, dtype=str)

    df = normalize_header(raw)
    df = df.dropna(how="all")

    col_prov = find_col(df, "province", "région", "region") or df.columns[0]
    col_nom = find_col(df, "établissement", "etablissement", "nom") or df.columns[1]
    col_cat = find_col(df, "catégorie", "categorie", "type") or df.columns[2]
    col_geo = find_col(df, "latitude", "longitude", "coord", "gps") or df.columns[3]

    out = pd.DataFrame(
        {
            "Province": df[col_prov].astype(str).str.strip(),
            "Établissement": df[col_nom].astype(str).str.strip(),
            "Catégorie": df[col_cat].astype(str).str.strip().str.capitalize(),
            "Coordonnées brutes": df[col_geo].astype(str).str.strip(),
        }
    )
    out = out[out["Établissement"].str.len() > 0]
    out = out[~out["Établissement"].str.lower().isin(["nan", "none"])]

    coords = out["Coordonnées brutes"].apply(parse_coords)
    out["lat"] = [c[0] for c in coords]
    out["lon"] = [c[1] for c in coords]

    # Harmonisation des libellés de catégorie (fautes de frappe fréquentes)
    fixes = {
        "Supermaché": "Supermarché",
        "Supermarche": "Supermarché",
        "Epicerie": "Épicerie",
        "Hotel": "Hôtel",
    }
    out["Catégorie"] = out["Catégorie"].replace(fixes)
    out["Catégorie"] = out["Catégorie"].replace({"": "Non renseignée", "Nan": "Non renseignée"})

    return out.reset_index(drop=True), source


# --------------------------------------------------------------------------- #
# Pré-souscripteurs eAriary
# --------------------------------------------------------------------------- #

def split_address(address):
    """Découpe « Anosibe, Antananarivo, Analamanga, Madagascar ».

    Retourne (localité, ville, région), du plus fin au plus large. Le dernier
    segment est le pays, l'avant-dernier la région — mais une adresse saisie
    sans virgule (« Ambondrona ») n'est qu'une localité : lui attribuer une
    région gonflerait le décompte des régions couvertes.
    """
    parts = [p.strip() for p in str(address).split(",") if p.strip()]
    structured = len(parts) > 1
    if structured and parts[-1].lower().startswith("madagas"):
        parts = parts[:-1]
    if not parts:
        return "Non renseignée", "Non renseignée", "Non renseignée"

    locality = parts[0]
    region = parts[-1] if structured else "Non renseignée"
    city = parts[-2] if len(parts) >= 2 else parts[0]
    return locality, city, region


@st.cache_data(ttl=300, show_spinner=False)
def load_subscribers():
    """Charge le fichier Excel des pré-souscripteurs et y joint les coordonnées.

    Retourne (DataFrame, message d'anomalie ou None). Le DataFrame est vide si
    le fichier est absent : l'application reste utilisable sans lui.
    """
    # L'agrégat l'emporte sur le classeur dès qu'il est le plus récent : c'est
    # le cas après un import fait depuis l'interface, qui réécrit l'agrégat mais
    # ne touche pas au classeur. Sans cette règle, l'application continuerait
    # d'afficher l'ancienne liste sans rien en dire.
    aggregate_plus_recent = (
        SUBSCRIBERS_AGGREGATE.exists()
        and SUBSCRIBERS_XLSX.exists()
        and SUBSCRIBERS_AGGREGATE.stat().st_mtime > SUBSCRIBERS_XLSX.stat().st_mtime
    )
    if SUBSCRIBERS_XLSX.exists() and not aggregate_plus_recent:
        try:
            raw = pd.read_excel(SUBSCRIBERS_XLSX, dtype=str)
        except Exception as exc:
            return pd.DataFrame(), f"Lecture impossible du fichier Excel ({exc})"
    elif SUBSCRIBERS_AGGREGATE.exists():
        # Repli sans donnée personnelle : chaque effectif est redéployé en
        # lignes individuelles pour que la suite du traitement soit identique.
        agg = pd.read_csv(SUBSCRIBERS_AGGREGATE, dtype=str)
        agg["Inscrits"] = pd.to_numeric(agg["Inscrits"], errors="coerce").fillna(0)
        raw = agg.loc[agg.index.repeat(agg["Inscrits"].astype(int))].drop(
            columns="Inscrits"
        )
    else:
        return pd.DataFrame(), (
            f"Pré-souscripteurs indisponibles : ni {SUBSCRIBERS_XLSX.name} ni "
            f"{SUBSCRIBERS_AGGREGATE.name} n'est présent."
        )

    # Index remis à plat : le repli agrégé duplique les libellés d'index.
    raw = raw.reset_index(drop=True)
    col_addr = find_col(raw, "adresse", "address") or raw.columns[0]
    col_type = find_col(raw, "account", "compte", "type") or raw.columns[-1]

    df = pd.DataFrame({"Adresse": raw[col_addr].astype(str).str.strip()})
    df = df[df["Adresse"].str.len() > 0]
    df = df[~df["Adresse"].str.lower().isin(["nan", "none"])]
    df["Adresse"] = df["Adresse"].mask(
        df["Adresse"].str.contains(EMAIL_LIKE), UNKNOWN_ADDRESS
    )

    account = raw.loc[df.index, col_type].astype(str).str.strip()
    account = account.replace({"Epicerie": "Épicerie", "Epicerie ": "Épicerie"})
    # Le fichier source contient quelques valeurs parasites (une adresse e-mail
    # dans la colonne « Account ») : tout ce qui sort du référentiel est neutralisé.
    df["Type de compte"] = account.where(account.isin(ACCOUNT_ORDER), "Non renseigné")

    parts = df["Adresse"].apply(split_address)
    df["Localité"] = [p[0] for p in parts]
    df["Ville"] = [p[1] for p in parts]
    df["Région"] = [p[2] for p in parts]

    warning = None
    if GEOCODE_CACHE.exists():
        geo = pd.read_csv(GEOCODE_CACHE, dtype=str)
        geo["lat"] = pd.to_numeric(geo["lat"], errors="coerce")
        geo["lon"] = pd.to_numeric(geo["lon"], errors="coerce")
        df = df.merge(
            geo[["Adresse", "lat", "lon", "precision"]], on="Adresse", how="left"
        )
        # Une adresse absente du cache est une adresse jamais résolue : sans ce
        # comblement, elle disparaîtrait du tableau des lignes non localisées,
        # qui regroupe par motif.
        df["precision"] = df["precision"].fillna("introuvable")
    else:
        df["lat"] = pd.NA
        df["lon"] = pd.NA
        df["precision"] = "introuvable"
        warning = (
            "Coordonnées des pré-souscripteurs indisponibles : lancez "
            "`python tools/geocode_souscripteurs.py` pour générer "
            f"`{GEOCODE_CACHE.relative_to(BASE_DIR)}`."
        )

    return df.reset_index(drop=True), warning


def aggregate_subscribers(df):
    """Regroupe les pré-souscripteurs par localité géolocalisée.

    Une ligne par point de la carte, avec le total et le détail par type de
    compte — aucune donnée nominative n'est conservée.
    """
    located = df.dropna(subset=["lat", "lon"])
    if located.empty:
        return pd.DataFrame(
            columns=["Localité", "Ville", "Région", "Inscrits", "lat", "lon", "Détail"]
        )

    counts = (
        located.groupby(["Adresse", "Localité", "Ville", "Région", "lat", "lon"])
        .size()
        .reset_index(name="Inscrits")
    )
    by_type = (
        located.groupby(["Adresse", "Type de compte"]).size().unstack(fill_value=0)
    )
    for account in ACCOUNT_ORDER + ["Non renseigné"]:
        if account not in by_type.columns:
            by_type[account] = 0
    by_type = by_type[ACCOUNT_ORDER + ["Non renseigné"]].reset_index()

    out = counts.merge(by_type, on="Adresse")
    out["Détail"] = out.apply(
        lambda r: " · ".join(
            f"{a} {int(r[a])}" for a in ACCOUNT_ORDER + ["Non renseigné"] if r[a]
        ),
        axis=1,
    )
    return out.sort_values("Inscrits", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Choroplèthe : classes, palette, légende, popups
# --------------------------------------------------------------------------- #

def zones_disponibles() -> bool:
    """Vrai si le module d'agrégation et les contours administratifs sont là."""
    if geo_aggregate is None:
        return False
    try:
        return bool(geo_aggregate.zones_disponibles())
    except Exception:
        return False


def fr_number(value, decimals=0):
    """Formate un nombre à la française : séparateur décimal virgule."""
    if value is None or pd.isna(value):
        return "—"
    text = f"{float(value):,.{decimals}f}"
    # Passage en une fois par un séparateur neutre, sinon les remplacements
    # successifs se marchent dessus (« 1,234.5 » -> « 1.234,5 »).
    return text.replace(",", " ").replace(".", ",")


def quantile_bounds(values, n_classes=ZONE_CLASSES, integer=True):
    """Bornes de classes en quantiles, dédoublonnées.

    Les intervalles égaux sont inutilisables ici : Antananarivo concentre près
    d'un tiers des inscrits et écraserait toutes les autres zones dans la
    classe basse. Les zéros sont exclus du calcul — ils ont leur propre teinte
    et fausseraient les quantiles, la majorité des zones étant à 0.

    Beaucoup de valeurs identiques produisent des quantiles identiques : sans
    dédoublonnage, `StepColormap` reçoit un index non strictement croissant et
    renvoie n'importe quelle couleur.
    """
    serie = pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce")
    serie = serie.dropna()
    serie = serie[serie > 0]
    if serie.empty:
        return []

    quantiles = np.quantile(
        serie.to_numpy(dtype=float), np.linspace(0.0, 1.0, n_classes + 1)
    )
    if integer:
        brutes = [float(round(float(q))) for q in quantiles]
    else:
        brutes = [round(float(q), 2) for q in quantiles]

    bounds = sorted(set(brutes))
    if len(bounds) == 1:
        # Une seule valeur distincte : on fabrique un intervalle d'un pas pour
        # que la classe unique reste colorable.
        pas = 1.0 if integer else 0.01
        bounds = [bounds[0], bounds[0] + pas]
    return bounds


def class_labels(bounds, integer=True, decimals=0):
    """Libellés lisibles des classes : « 1–3 », « 4–9 », « 10–27 »…

    Une échelle continue serait illisible : ce sont les bornes réellement
    utilisées qui sont affichées, et les classes entières sont exprimées en
    intervalles inclusifs (la borne basse suit la borne haute précédente).
    """
    labels = []
    for i in range(len(bounds) - 1):
        bas, haut = bounds[i], bounds[i + 1]
        if integer:
            bas_i = int(round(bas)) if i == 0 else int(round(bas)) + 1
            haut_i = int(round(haut))
            bas_i = min(bas_i, haut_i)
            labels.append(
                fr_number(bas_i)
                if bas_i == haut_i
                else f"{fr_number(bas_i)}–{fr_number(haut_i)}"
            )
        else:
            labels.append(
                f"{fr_number(bas, decimals)}–{fr_number(haut, decimals)}"
            )
    return labels


def zone_popup_html(zones, niveau, metric_col, metric_label, decimals, unite):
    """Pré-calcule le bloc HTML du popup de chaque zone.

    `GeoJsonPopup` ne sait qu'insérer des propriétés du GeoJSON dans un
    tableau : on lui passe donc un unique champ déjà mis en forme, cohérent
    avec les popups des marqueurs d'établissement. La mise en forme passe par
    les classes de `MAP_ZONE_CSS` — au niveau Commune, des attributs `style`
    répétés 1600 fois pèseraient plus lourd que les géométries elles-mêmes.
    """
    blocs = []
    for z in zones.itertuples(index=False):
        nom = html.escape(str(getattr(z, "nom_zone", "") or "—"))
        parent = str(getattr(z, "nom_parent", "") or "").strip()
        situe = f"{niveau} · {html.escape(parent)}" if parent else niveau
        inscrits = int(getattr(z, "inscrits", 0) or 0)
        etabs = int(getattr(z, "etablissements", 0) or 0)
        localites = int(getattr(z, "localites", 0) or 0)
        part = getattr(z, "part_pct", None)
        ratio = getattr(z, "ratio_inscrits_etab", None)
        approx = int(getattr(z, "rattachement_approx_n", 0) or 0)

        # Chaînes déjà échappées par `geo_aggregate` : ne pas ré-échapper.
        det_loc = str(getattr(z, "localites_detail", "") or "").strip()
        det_etab = str(getattr(z, "etablissements_detail", "") or "").strip()

        lignes = [f'<div class="zpop-h">{nom}</div>', f'<div class="zpop-s">{situe}</div>']

        if inscrits:
            lignes.append(
                f'<div class="zpop-n">{fr_number(inscrits)} '
                f"pré-souscripteur{'s' if inscrits > 1 else ''}</div>"
            )
            if det_loc:
                lignes.append(
                    f'<div class="zpop-r"><b>{fr_number(localites)} localité(s)</b> :'
                    f" {det_loc}</div>"
                )
        else:
            lignes.append('<div class="zpop-r">Aucun pré-souscripteur rattaché.</div>')

        lignes.append(
            f'<div class="zpop-r"><b>{fr_number(etabs)} établissement(s)</b>'
            + (f" : {det_etab}" if det_etab else "")
            + "</div>"
        )
        if inscrits:
            ratio_txt = (
                "non calculable (aucun établissement)"
                if ratio is None or pd.isna(ratio)
                else f"{fr_number(ratio, 2)} inscrit(s) par établissement"
            )
            lignes.append(f'<div class="zpop-d">Densité : {ratio_txt}</div>')
            if part is not None and not pd.isna(part):
                lignes.append(
                    f'<div class="zpop-d">Part du total : {fr_number(part, 2)} %</div>'
                )
            # Métrique hors des trois toujours affichées : on l'ajoute pour que
            # le popup explique toujours la couleur de la zone.
            if metric_col not in ("inscrits", "part_pct", "ratio_inscrits_etab"):
                lignes.append(
                    f'<div class="zpop-d">{html.escape(metric_label)} : '
                    f"{fr_number(getattr(z, metric_col, None), decimals)} "
                    f"{html.escape(unite)}</div>"
                )
            if approx:
                lignes.append(
                    f'<div class="zpop-a">{fr_number(approx)} inscrit(s) '
                    "rattaché(s) de façon approximative.</div>"
                )

        bloc = '<div class="zpop">' + "".join(lignes) + "</div>"
        # Folium injecte la propriété dans un littéral de gabarit JavaScript :
        # un accent grave ou un « ${ } » dans un nom de zone casserait le script.
        blocs.append(bloc.replace("`", "'").replace("${", "$ {"))
    return blocs


def zone_legend_html(labels, couleurs, titre, extras=()):
    """Légende de la choroplèthe, avec le même vocabulaire visuel que le reste.

    Chaque pastille porte son intervalle : la couleur n'est jamais la seule
    information portée par la carte.
    """
    items = "".join(
        '<span class="legend-item">'
        f'<span class="swatch zone" style="background:{couleur}"></span>{label}</span>'
        for label, couleur in zip(labels, couleurs)
    )
    for libelle, couleur, tirete in extras:
        bordure = f"border:1px dashed {ZONE_ZERO_STROKE}" if tirete else "border:none"
        items += (
            '<span class="legend-item">'
            f'<span class="swatch zone" style="background:{couleur};{bordure}"></span>'
            f"{libelle}</span>"
        )
    return (
        f'<div class="legend-title">{titre}</div>'
        f'<div class="legend">{items}</div>'
    )


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="Carte des établissements — Madagascar",
    page_icon=":material/location_on:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Retouches ciblées : Streamlit gère déjà couleurs, polices et rayons via
# .streamlit/config.toml — on ne complète ici que ce que le thème n'expose pas.
st.html(
    """
    <style>
      /* Respiration verticale et largeur de lecture confortable */
      [data-testid="stMainBlockContainer"] { padding-top: 4.5rem; max-width: 1400px; }

      /* En-tête de page */
      .page-header { margin-bottom: .25rem; }
      .page-header h1 {
        font-size: 1.9rem; font-weight: 700; letter-spacing: -.02em;
        margin: 0; color: #0F172A;
      }
      .page-header p {
        margin: .35rem 0 0; color: #475569; font-size: .95rem; max-width: 65ch;
      }

      /* Pastille de provenance des données */
      .source-badge {
        display: inline-flex; align-items: center; gap: .45rem;
        padding: .3rem .7rem; border-radius: 999px;
        border: 1px solid #E2E8F0; background: #F8FAFC;
        font-size: .8rem; color: #334155; white-space: nowrap;
      }
      .source-badge .dot {
        width: .5rem; height: .5rem; border-radius: 50%; flex: none;
      }
      .dot-live { background: #16A34A; }
      .dot-fallback { background: #D97706; }

      /* Cartes d'indicateurs : chiffres alignés, libellés discrets */
      [data-testid="stMetric"] {
        padding: 1rem 1.15rem; background: #FFFFFF;
        transition: border-color .18s ease, box-shadow .18s ease;
      }
      [data-testid="stMetric"]:hover {
        border-color: #CBD5E1; box-shadow: 0 1px 3px rgb(15 23 42 / .07);
      }
      [data-testid="stMetricValue"] {
        font-variant-numeric: tabular-nums; letter-spacing: -.02em;
      }
      [data-testid="stMetricLabel"] p {
        font-size: .8rem; font-weight: 500; color: #64748B;
        text-transform: uppercase; letter-spacing: .04em;
      }

      /* Légende de la carte */
      .legend { display: flex; flex-wrap: wrap; gap: .45rem; margin: .85rem 0 .25rem; }
      .legend-item {
        display: inline-flex; align-items: center; gap: .45rem;
        padding: .32rem .7rem; border-radius: 999px;
        border: 1px solid #E2E8F0; background: #FFFFFF;
        font-size: .82rem; color: #334155;
      }
      .legend-item .swatch {
        width: .6rem; height: .6rem; border-radius: 50%; flex: none;
      }
      /* Pastille carrée pour les surfaces : un aplat de zone n'est pas un point */
      .legend-item .swatch.zone {
        width: .85rem; height: .85rem; border-radius: .15rem;
      }
      .legend-title {
        margin: .85rem 0 0; font-size: .8rem; font-weight: 600; color: #475569;
        text-transform: uppercase; letter-spacing: .04em;
      }
      .legend-title + .legend { margin-top: .4rem; }

      /* Titres de section plus calmes que le titre de page */
      .section-title {
        font-size: 1.05rem; font-weight: 600; color: #0F172A;
        margin: 2rem 0 .2rem;
      }
      .section-title + .section-sub {
        margin: 0 0 .75rem; color: #64748B; font-size: .875rem;
      }
      /* Le premier titre d'une vue n'a rien au-dessus de lui : la marge haute
         des sections y creuserait un vide sous le sélecteur de vue. */
      [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"]
        > [data-testid="stElementContainer"]:nth-child(2) .section-title {
        margin-top: 1rem;
      }

      /* La carte Folium adopte le rayon et la bordure du reste de l'UI */
      iframe[title="streamlit_folium.st_folium"] {
        border: 1px solid #E2E8F0; border-radius: .5rem;
      }

      @media (max-width: 640px) {
        [data-testid="stMainBlockContainer"] { padding-top: 3.5rem; }
        .page-header h1 { font-size: 1.5rem; }
      }
      @media (prefers-reduced-motion: reduce) {
        [data-testid="stMetric"] { transition: none; }
      }
    </style>
    """
)

data, source = load_data()
unlocated = data[data["lat"].isna()]
is_live = source.startswith("Google Sheet")

subscribers, sub_warning = load_subscribers()
has_subscribers = not subscribers.empty

head_left, head_right = st.columns([3, 1], vertical_alignment="center")
with head_left:
    st.html(
        """
        <div class="page-header">
          <h1>Carte des établissements</h1>
          <p>Réseau de partenaires à Madagascar — filtrez par ville, catégorie
             ou nom, puis explorez la carte ou exportez la sélection.</p>
        </div>
        """
    )
with head_right:
    st.html(
        f"""
        <div style="text-align:right">
          <span class="source-badge">
            <span class="dot {'dot-live' if is_live else 'dot-fallback'}"></span>
            {source}
          </span>
        </div>
        """
    )

# ------------------------------- Filtres ---------------------------------- #
with st.sidebar:
    st.subheader("Filtres")

    # Par défaut aucune puce n'est sélectionnée : le panneau reste lisible et
    # une sélection vide affiche déjà l'ensemble des données.
    provinces = sort_fr(data["Province"].unique())
    sel_prov = st.multiselect(
        "Province / ville",
        provinces,
        default=[],
        placeholder="Toutes les villes",
        help="Aucune sélection équivaut à toutes les villes.",
    )

    categories = sort_fr(data["Catégorie"].unique())
    sel_cat = st.multiselect(
        "Catégorie",
        categories,
        default=[],
        placeholder="Toutes les catégories",
        help="Aucune sélection équivaut à toutes les catégories.",
    )

    query = st.text_input(
        "Recherche par nom",
        "",
        placeholder="Nom de l'établissement",
    ).strip().lower()

    if has_subscribers:
        st.divider()
        st.subheader("Pré-souscripteurs eAriary")
        show_subs = st.toggle(
            "Afficher sur la carte",
            value=True,
            help=(
                "Choroplèthe des inscrits par zone administrative."
                if zones_disponibles()
                else "Cercles proportionnels au nombre d'inscrits par localité."
            ),
        )

        sub_regions = sort_fr(subscribers["Région"].unique())
        sel_sub_reg = st.multiselect(
            "Région",
            sub_regions,
            default=[],
            placeholder="Toutes les régions",
            help="Aucune sélection équivaut à toutes les régions.",
        )

        sub_types = [t for t in ACCOUNT_ORDER + ["Non renseigné"]
                     if t in set(subscribers["Type de compte"])]
        sel_sub_type = st.multiselect(
            "Type de compte",
            sub_types,
            default=[],
            placeholder="Tous les types",
            help="Aucune sélection équivaut à tous les types.",
        )

        n_uncertain = int((subscribers["precision"] == "incertaine").sum())
        include_uncertain = st.checkbox(
            f"Inclure les adresses incertaines ({n_uncertain})",
            value=False,
            help="Adresses saisies sans ville ni région : le géocodeur renvoie "
                 "toujours un point à Madagascar, sans garantie qu'il soit le bon.",
            disabled=n_uncertain == 0,
        )
    else:
        show_subs, sel_sub_reg, sel_sub_type = False, [], []
        include_uncertain = False

    st.divider()
    st.subheader("Données")
    st.caption(f"Source des données : {source}")
    if st.button(
        "Recharger les données",
        icon=":material/refresh:",
        width="stretch",
        help="Vide le cache (5 min) et relit le Google Sheet.",
    ):
        st.cache_data.clear()
        st.rerun()

# Une sélection vide = aucun filtre actif, donc on affiche tout.
if not sel_prov:
    sel_prov = provinces
if not sel_cat:
    sel_cat = categories

mask = data["Province"].isin(sel_prov) & data["Catégorie"].isin(sel_cat)
if query:
    mask &= data["Établissement"].str.lower().str.contains(query, na=False)

filtered = data[mask]
filtered_located = filtered.dropna(subset=["lat", "lon"])

if has_subscribers:
    sub_mask = pd.Series(True, index=subscribers.index)
    if sel_sub_reg:
        sub_mask &= subscribers["Région"].isin(sel_sub_reg)
    if sel_sub_type:
        sub_mask &= subscribers["Type de compte"].isin(sel_sub_type)
    subs_filtered = subscribers[sub_mask].copy()
    # Écartées de la carte comme des lignes non localisées : leur point existe
    # mais ne veut rien dire tant que l'adresse n'a pas été précisée.
    if not include_uncertain:
        drop = subs_filtered["precision"] == "incertaine"
        subs_filtered.loc[drop, ["lat", "lon"]] = pd.NA
else:
    subs_filtered = subscribers
subs_points = aggregate_subscribers(subs_filtered)

# ------------------------------- Onglets ----------------------------------- #
# Quatre entrées plutôt qu'une page unique de deux mille lignes : la carte et
# ses indicateurs, le détail des établissements, les pré-inscrits (bilan et
# import), et le code d'intégration. Les filtres restent dans la barre
# latérale, communs aux vues — c'est le même jeu de données qu'on regarde sous
# quatre angles, pas quatre pages.
#
# Un sélecteur plutôt que `st.tabs` : celui-ci rend les quatre panneaux d'un
# coup, y compris masqués. Un tableau mesuré alors que son onglet est caché
# s'installe à 49 px de large et n'en bouge plus, et la carte se reconstruit à
# chaque clic même quand personne ne la regarde. Ici, seule la vue demandée est
# construite ; changer de vue relance le script, sur des données déjà en cache.
VUES = ["Carte", "Établissements", "Pré-inscrits", "Intégration"]
vue = st.segmented_control(
    "Vue", VUES, default=VUES[0], key="vue", label_visibility="collapsed"
) or VUES[0]

if vue == "Carte":
    # ------------------------------- Indicateurs ------------------------------- #
    c1, c2, c3, c4 = st.columns(4, gap="medium")
    c1.metric("Établissements", len(filtered), border=True)
    c2.metric("Géolocalisés", len(filtered_located), border=True)
    c3.metric("Sans coordonnées", len(filtered) - len(filtered_located), border=True)
    c4.metric("Villes couvertes", filtered["Province"].nunique(), border=True)

    if sub_warning:
        st.warning(sub_warning, icon=":material/warning:")

    # ------------------ Contrôles de la choroplèthe (haut de page) -------------- #
    # Ces réglages pilotent la carte : ils restent dans le flux principal, à côté
    # du résultat qu'ils modifient, et non dans le panneau latéral des filtres.
    CHORO_LEVELS = ["Région", "District", "Commune"]
    if geo_aggregate is not None:
        CHORO_LEVELS = list(geo_aggregate.NIVEAUX) or CHORO_LEVELS

    CHORO_READY = has_subscribers and zones_disponibles()

    niveau = CHORO_LEVELS[0]
    metric_label = next(iter(ZONE_METRICS))
    metric_col, metric_decimals, metric_unit, _ = ZONE_METRICS[metric_label]
    show_etabs = True
    sel_cat_zone = []
    zones = None
    zones_detail = None

    if has_subscribers:
        st.html(
            '<div class="section-title">Couverture des pré-souscripteurs</div>'
            '<div class="section-sub">Les inscrits sont agrégés par zone '
            "administrative ; les établissements partenaires restent des marqueurs "
            "posés au-dessus des zones.</div>"
        )

        if geo_aggregate is None:
            st.warning(
                "Module `geo_aggregate` introuvable : la carte retombe sur les "
                "cercles proportionnels par localité.",
                icon=":material/warning:",
            )
        elif not CHORO_READY:
            st.warning(
                "Contours administratifs absents : lancez "
                "`python tools/fetch_boundaries.py` pour générer "
                "`data/geo/mdg_adm*.geojson`. En attendant, la carte retombe sur "
                "les cercles proportionnels par localité.",
                icon=":material/warning:",
            )

        ctl1, ctl2, ctl3, ctl4 = st.columns([1.4, 1.3, 1.3, 0.9], gap="medium")
        with ctl1:
            niveau = st.radio(
                "Découpage",
                CHORO_LEVELS,
                index=0,
                horizontal=True,
                disabled=not CHORO_READY,
                help="Finesse des zones coloriées. La commune est le niveau le "
                     "plus lourd à dessiner.",
            )
        with ctl2:
            metric_label = st.selectbox(
                "Métrique de coloriage",
                list(ZONE_METRICS),
                index=0,
                disabled=not CHORO_READY,
                help="Détermine à la fois la couleur des zones et la légende.",
            )
            metric_col, metric_decimals, metric_unit, metric_help = ZONE_METRICS[metric_label]
            st.caption(metric_help)
        with ctl3:
            cats_zone = [c for c in (
                geo_aggregate.CATEGORIES if geo_aggregate is not None else []
            ) if c in set(data["Catégorie"])] or sort_fr(data["Catégorie"].unique())
            sel_cat_zone = st.multiselect(
                "Catégorie d'établissement",
                cats_zone,
                default=[],
                placeholder="Toutes les catégories",
                help="Restreint les établissements comptés dans la densité et "
                     "dessinés sur la carte. Aucune sélection équivaut à toutes "
                     "les catégories. Se combine au filtre du panneau latéral.",
            )
        with ctl4:
            show_etabs = st.toggle(
                "Afficher les établissements",
                value=True,
                help="Masque les marqueurs pour lire les zones sans obstruction.",
            )

    # Établissements retenus pour l'agrégation et pour les marqueurs : filtre
    # latéral d'abord, puis restriction de catégorie propre à la choroplèthe.
    etabs_zone = filtered_located
    if sel_cat_zone:
        etabs_zone = etabs_zone[etabs_zone["Catégorie"].isin(sel_cat_zone)]

    if CHORO_READY:
        try:
            zones, zones_detail = geo_aggregate.aggregate(subs_filtered, etabs_zone, niveau)
        except Exception as exc:
            st.warning(
                f"Agrégation par {niveau.lower()} impossible ({exc}) : repli sur "
                "les cercles proportionnels par localité.",
                icon=":material/warning:",
            )
            zones, zones_detail = None, None
            CHORO_READY = False

    # ------------------------ Indicateurs par zone ----------------------------- #
    draw_zones = CHORO_READY and zones is not None and not zones.empty

    if draw_zones:
        zone_inscrits = pd.to_numeric(zones["inscrits"], errors="coerce").fillna(0)
        total_inscrits = int(zone_inscrits.sum())
        n_zones = len(zones)
        n_couvertes = int((zone_inscrits > 0).sum())
        taux = (n_couvertes / n_zones * 100) if n_zones else 0.0
        top_idx = zone_inscrits.idxmax() if n_couvertes else None
        top_nom = str(zones.loc[top_idx, "nom_zone"]) if top_idx is not None else "—"
        top_val = int(zone_inscrits.loc[top_idx]) if top_idx is not None else 0
        # 150 noms de communes sont des homonymes et les arrondissements
        # d'Antananarivo s'appellent « 1er Arrondissement » : le parent est
        # indispensable pour que l'indicateur désigne une zone sans ambiguïté.
        top_parent = (
            str(zones.loc[top_idx, "nom_parent"] or "").strip()
            if top_idx is not None
            else ""
        )
        top_complet = f"{top_nom} ({top_parent})" if top_parent else top_nom

        z1, z2, z3, z4 = st.columns(4, gap="medium")
        z1.metric("Inscrits localisés", fr_number(total_inscrits), border=True)
        z2.metric(
            "Zones couvertes",
            fr_number(n_couvertes),
            border=True,
            help=f"{niveau}s comptant au moins un inscrit, sur "
                 f"{fr_number(n_zones)} au total.",
        )
        z3.metric(
            f"{niveau} n°1",
            top_nom if len(top_nom) <= 22 else top_nom[:21] + "…",
            delta=f"{fr_number(top_val)} inscrits",
            delta_color="off",
            border=True,
            help=top_complet,
        )
        z4.metric(
            "Taux de couverture",
            f"{fr_number(taux, 1)} %",
            border=True,
            help=f"{fr_number(n_couvertes)} zone(s) couverte(s) sur "
                 f"{fr_number(n_zones)} au niveau {niveau.lower()}.",
        )
    elif has_subscribers:
        # Repli : les indicateurs par localité, comme avant la choroplèthe.
        s1, s2, s3, s4 = st.columns(4, gap="medium")
        s1.metric("Pré-souscripteurs", len(subs_filtered), border=True)
        s2.metric("Positionnés", int(subs_points["Inscrits"].sum()), border=True)
        s3.metric("Localités", len(subs_points), border=True)
        s4.metric("Régions couvertes", subs_filtered["Région"].nunique(), border=True)

    # --------------------------------- Carte ----------------------------------- #
    try:
        import folium
        from folium.plugins import MarkerCluster
        from streamlit_folium import st_folium

        HAS_FOLIUM = True
    except ImportError:
        HAS_FOLIUM = False

    # Choroplèthe si les contours sont là, cercles proportionnels sinon.
    draw_choro = bool(show_subs) and draw_zones
    draw_subs = bool(show_subs) and not draw_zones and not subs_points.empty
    draw_etabs = bool(show_etabs) and not etabs_zone.empty
    map_empty = not draw_etabs and not draw_subs and not draw_choro

    if map_empty:
        st.html('<div class="section-title">Carte</div>')
        st.info(
            "Rien à afficher : aucune couche n'est activée, ou les filtres actuels "
            "ne laissent aucun point. Réactivez une couche ci-dessus ou élargissez "
            "la sélection dans le panneau latéral.",
            icon=":material/filter_alt_off:",
        )
    elif HAS_FOLIUM:
        counts = []
        if draw_etabs:
            counts.append(f"{len(etabs_zone)} établissement(s) positionné(s)")
        if draw_choro:
            counts.append(
                f"{fr_number(int(zone_inscrits.sum()))} inscrit(s) "
                f"sur {fr_number(n_couvertes)} {niveau.lower()}(s)"
            )
        if draw_subs:
            counts.append(
                f"{int(subs_points['Inscrits'].sum())} pré-souscripteur(s) "
                f"sur {len(subs_points)} localité(s)"
            )
        clic = (
            f"Cliquez une zone pour son détail sous la carte, un marqueur pour la "
            "fiche de l'établissement."
            if draw_choro
            else "Cliquez un marqueur ou un cercle pour le détail."
        )
        st.html(
            '<div class="section-title">Carte</div>'
            f'<div class="section-sub">{" — ".join(counts)}. {clic}</div>'
        )

        # ------------------- Classes, palette et légende des zones -------------- #
        zone_bounds, zone_colors, zone_scale = [], [], None
        if draw_choro:
            zone_values = pd.to_numeric(zones[metric_col], errors="coerce")
            zone_bounds = quantile_bounds(
                zone_values, ZONE_CLASSES, integer=(metric_decimals == 0)
            )
            zone_colors = ZONE_RAMPS.get(
                max(len(zone_bounds) - 1, 1), ZONE_RAMPS[ZONE_CLASSES]
            )[: max(len(zone_bounds) - 1, 1)]
            if len(zone_bounds) >= 2:
                from branca.colormap import StepColormap

                zone_scale = StepColormap(
                    zone_colors,
                    index=zone_bounds,
                    vmin=zone_bounds[0],
                    vmax=zone_bounds[-1],
                )

        # Légende avant la carte : lisible sans faire défiler, et chaque pastille
        # porte son libellé — la couleur n'est jamais la seule information.
        if draw_choro:
            extras = [("Aucun inscrit", ZONE_ZERO_FILL, True)]
            if metric_col == "ratio_inscrits_etab":
                n_na = int(
                    ((zone_inscrits > 0) & zone_values.isna()).sum()
                )
                if n_na:
                    extras.append(
                        (f"Non calculable ({fr_number(n_na)})", ZONE_NA_FILL, True)
                    )
            st.html(
                zone_legend_html(
                    class_labels(
                        zone_bounds,
                        integer=(metric_decimals == 0),
                        decimals=metric_decimals,
                    ),
                    zone_colors,
                    f"{metric_unit[:1].upper()}{metric_unit[1:]} par {niveau.lower()}",
                    extras,
                )
            )

        legend_items = "".join(
            f'<span class="legend-item">'
            f'<span class="swatch" style="background:{CATEGORY_STYLE.get(c, DEFAULT_STYLE)[2]}"></span>'
            f"{c}</span>"
            for c in (sort_fr(etabs_zone["Catégorie"].unique()) if draw_etabs else [])
        )
        if draw_subs:
            legend_items += (
                f'<span class="legend-item">'
                f'<span class="swatch" style="background:{SUBSCRIBER_COLOR};'
                'opacity:.55;border:1px solid ' + SUBSCRIBER_COLOR + '"></span>'
                "Pré-souscripteurs (taille = nombre d'inscrits)</span>"
            )
        if legend_items:
            st.html(
                '<div class="legend-title">Établissements partenaires</div>'
                f'<div class="legend">{legend_items}</div>'
                if draw_choro
                else f'<div class="legend">{legend_items}</div>'
            )

        all_points = pd.concat(
            ([etabs_zone[["lat", "lon"]]] if draw_etabs else [])
            + ([subs_points[["lat", "lon"]]] if draw_subs else [])
        ) if (draw_etabs or draw_subs) else pd.DataFrame(columns=["lat", "lon"])
        if len(all_points):
            center = [all_points["lat"].mean(), all_points["lon"].mean()]
        else:
            minx, miny, maxx, maxy = zones.total_bounds
            center = [(miny + maxy) / 2, (minx + maxx) / 2]
        fmap = folium.Map(location=center, zoom_start=6, tiles=None, control_scale=True)
        fmap.get_root().header.add_child(folium.Element(MAP_ICON_FIX))
        if draw_choro:
            fmap.get_root().header.add_child(folium.Element(MAP_ZONE_CSS))

        # Fond clair par défaut : les marqueurs colorés priment sur le décor.
        # show=False sur les autres, sinon le dernier fond ajouté s'affiche par-dessus.
        folium.TileLayer("CartoDB positron", name="Plan clair").add_to(fmap)
        folium.TileLayer("OpenStreetMap", name="Plan détaillé", show=False).add_to(fmap)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri",
            name="Satellite",
            show=False,
        ).add_to(fmap)

        # --------------------- Couche choroplèthe des zones -------------------- #
        # Ajoutée avant les marqueurs : Leaflet empile dans l'ordre d'ajout, les
        # établissements doivent rester cliquables au-dessus des polygones.
        if draw_choro:
            zones_light = zones.copy()
            zones_light["popup_zone"] = zone_popup_html(
                zones, niveau, metric_col, metric_label, metric_decimals, metric_unit
            )
            zones_light["valeur_zone"] = pd.to_numeric(
                zones_light[metric_col], errors="coerce"
            )
            zones_light["inscrits_zone"] = zone_inscrits.astype(int).to_numpy()
            # Le nom seul ne suffit pas à désigner une zone : 150 communes sont
            # homonymes et Antananarivo compte six « n-e Arrondissement ». Le parent
            # accompagne donc le nom dès qu'il en existe un (tous les niveaux sauf
            # Région).
            zones_light["parent_zone"] = (
                zones["nom_parent"].fillna("").astype(str).str.strip().to_numpy()
            )
            # Seules les propriétés utiles à l'infobulle, au popup et au style sont
            # sérialisées : la géométrie communale est déjà lourde à transporter.
            colonnes_light = [
                "code_zone",
                "nom_zone",
                "inscrits_zone",
                "valeur_zone",
                "popup_zone",
                "geometry",
            ]
            montre_parent = bool(zones_light["parent_zone"].str.len().gt(0).any())
            if montre_parent:
                colonnes_light.insert(2, "parent_zone")
            zones_light = zones_light[colonnes_light].reset_index(
                drop=True
            )  # folium identifie les entités par leur index

            def style_zone(feature):
                """Remplissage de la zone selon la métrique choisie."""
                props = feature["properties"]
                valeur = props.get("valeur_zone")
                inscrits = props.get("inscrits_zone") or 0
                if (
                    zone_scale is None
                    or valeur is None
                    or pd.isna(valeur)
                    or float(valeur) <= 0
                ):
                    # Contour tireté et remplissage plus clair : le « rien » se lit
                    # aussi sans percevoir la nuance de couleur. Le second gris est
                    # réservé à la densité — seule métrique dont la légende annonce
                    # une classe « non calculable ».
                    return {
                        "fillColor": ZONE_NA_FILL
                        if (inscrits and metric_col == "ratio_inscrits_etab")
                        else ZONE_ZERO_FILL,
                        "color": ZONE_ZERO_STROKE,
                        "weight": 0.6,
                        "dashArray": "3,3",
                        "fillOpacity": 0.45,
                    }
                return {
                    # `rgb_hex_str` plutôt que l'appel direct : celui-ci renvoie un
                    # hexadécimal sur 8 chiffres que Leaflet interprète mal.
                    "fillColor": zone_scale.rgb_hex_str(float(valeur)),
                    "color": "#FFFFFF",
                    "weight": 0.7,
                    "fillOpacity": 0.78,
                }

            def highlight_zone(_feature):
                """Survol : bordure épaissie, sans changer le remplissage."""
                return {"weight": 3, "color": "#0F172A", "dashArray": ""}

            folium.GeoJson(
                zones_light,
                name=f"Inscrits par {niveau.lower()}",
                style_function=style_zone,
                highlight_function=highlight_zone,
                smooth_factor=1.0,
                tooltip=folium.GeoJsonTooltip(
                    fields=(
                        ["nom_zone", "parent_zone", "inscrits_zone"]
                        if montre_parent
                        else ["nom_zone", "inscrits_zone"]
                    ),
                    aliases=(
                        [f"{niveau} :", "Dans :", "Inscrits :"]
                        if montre_parent
                        else [f"{niveau} :", "Inscrits :"]
                    ),
                    localize=True,
                    sticky=True,
                ),
                popup=folium.GeoJsonPopup(
                    fields=["popup_zone"],
                    labels=False,
                    max_width=340,
                ),
            ).add_to(fmap)

        cluster = MarkerCluster(name="Établissements").add_to(fmap)

        for _, row in (etabs_zone.iterrows() if draw_etabs else iter(())):
            color, icon, hexcolor = CATEGORY_STYLE.get(row["Catégorie"], DEFAULT_STYLE)
            popup_html = f"""
                <div style="font-family:Inter,system-ui,sans-serif;min-width:224px;color:#0F172A">
                  <div style="font-size:14px;font-weight:600;line-height:1.35">
                    {row['Établissement']}
                  </div>
                  <div style="display:inline-flex;align-items:center;gap:6px;margin:6px 0 8px;
                              padding:2px 8px;border-radius:999px;background:#F1F5F9;
                              font-size:11px;color:#334155">
                    <span style="width:7px;height:7px;border-radius:50%;background:{hexcolor}"></span>
                    {row['Catégorie']}
                  </div>
                  <div style="font-size:12px;color:#475569">{row['Province']}</div>
                  <div style="font-family:'Source Code Pro',monospace;font-size:11px;
                              color:#64748B;margin-top:2px">
                    {row['lat']:.6f}, {row['lon']:.6f}
                  </div>
                  <a href="https://www.google.com/maps?q={row['lat']},{row['lon']}"
                     target="_blank" rel="noopener"
                     style="display:inline-block;margin-top:10px;padding:6px 12px;
                            background:#1E40AF;color:#FFFFFF;border-radius:6px;
                            font-size:12px;font-weight:500;text-decoration:none">
                    Ouvrir dans Google Maps
                  </a>
                </div>
            """
            folium.Marker(
                location=[row["lat"], row["lon"]],
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=row["Établissement"],
                icon=folium.Icon(color=color, icon=icon, prefix="fa"),
            ).add_to(cluster)

        # ----------------------- Couche pré-souscripteurs ---------------------- #
        if draw_subs:
            subs_layer = folium.FeatureGroup(name="Pré-souscripteurs eAriary")
            biggest = int(subs_points["Inscrits"].max())

            for _, row in subs_points.iterrows():
                count = int(row["Inscrits"])
                # Rayon en racine carrée : c'est l'aire du disque, et non son rayon,
                # qui reste proportionnelle au nombre d'inscrits.
                radius = 7 + 21 * (count / biggest) ** 0.5
                place = row["Localité"]
                if row["Ville"] and row["Ville"] != row["Localité"]:
                    place = f"{place}, {row['Ville']}"

                popup_html = f"""
                    <div style="font-family:Inter,system-ui,sans-serif;min-width:210px;color:#0F172A">
                      <div style="font-size:14px;font-weight:600;line-height:1.35">{place}</div>
                      <div style="font-size:12px;color:#475569;margin-top:2px">{row['Région']}</div>
                      <div style="display:inline-flex;align-items:center;gap:6px;margin:8px 0 6px;
                                  padding:2px 8px;border-radius:999px;background:#EEF2FF;
                                  font-size:11px;color:#3730A3;font-weight:500">
                        <span style="width:7px;height:7px;border-radius:50%;background:{SUBSCRIBER_COLOR}"></span>
                        {count} pré-souscripteur{'s' if count > 1 else ''}
                      </div>
                      <div style="font-size:12px;color:#334155">{row['Détail']}</div>
                    </div>
                """
                folium.CircleMarker(
                    location=[row["lat"], row["lon"]],
                    radius=radius,
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=f"{place} — {count} inscrit(s)",
                    color=SUBSCRIBER_COLOR,
                    weight=1.5,
                    fill=True,
                    fill_color=SUBSCRIBER_COLOR,
                    fill_opacity=0.35,
                ).add_to(subs_layer)

            subs_layer.add_to(fmap)

        if len(all_points) > 1:
            fmap.fit_bounds(all_points.values.tolist(), padding=(30, 30))
        elif draw_choro:
            minx, miny, maxx, maxy = zones.total_bounds
            fmap.fit_bounds([[miny, minx], [maxy, maxx]], padding=(20, 20))

        folium.LayerControl(collapsed=True).add_to(fmap)
        # `last_active_drawing` seul : tout autre objet retourné (bornes, zoom)
        # déclencherait un rerun à chaque déplacement de la carte.
        map_state = st_folium(
            fmap,
            use_container_width=True,
            height=580,
            returned_objects=["last_active_drawing"] if draw_choro else [],
        )

        # ------------------- Panneau de détail de la zone cliquée --------------- #
        if draw_choro:
            drawing = (map_state or {}).get("last_active_drawing") or {}
            # On identifie la zone par son code, jamais par un index de ligne :
            # `last_active_drawing` ne renvoie qu'un objet GeoJSON isolé.
            code_clique = (drawing.get("properties") or {}).get("code_zone")
            zone_row = (
                zones[zones["code_zone"] == code_clique]
                if code_clique is not None
                else zones.iloc[0:0]
            )

            if zone_row.empty:
                st.info(
                    f"Cliquez une {niveau.lower()} sur la carte pour afficher le "
                    "détail de ses localités et l'exporter.",
                    icon=":material/ads_click:",
                )
            else:
                nom_clique = str(zone_row.iloc[0]["nom_zone"])
                nb_clique = int(pd.to_numeric(zone_row.iloc[0]["inscrits"], errors="coerce") or 0)
                lignes = (
                    zones_detail[zones_detail["code_zone"] == code_clique]
                    if zones_detail is not None and not zones_detail.empty
                    else pd.DataFrame()
                )
                st.html(
                    f'<div class="section-title">{html.escape(nom_clique)}</div>'
                    f'<div class="section-sub">{fr_number(nb_clique)} inscrit(s) '
                    f"répartis sur {fr_number(len(lignes))} localité(s) — cliquez un "
                    "en-tête pour trier.</div>"
                )
                if lignes.empty:
                    st.info(
                        "Aucune localité rattachée à cette zone avec les filtres "
                        "actuels.",
                        icon=":material/search_off:",
                    )
                else:
                    cols = [
                        c
                        for c in ["Localité", "Ville", "Région", "inscrits",
                                  "rattachement_approx"]
                        if c in lignes.columns
                    ]
                    table = lignes[cols].sort_values("inscrits", ascending=False)
                    st.dataframe(
                        table,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Localité": st.column_config.TextColumn(
                                "Localité", width="medium"
                            ),
                            "Ville": st.column_config.TextColumn("Ville", width="medium"),
                            "Région": st.column_config.TextColumn("Région", width="medium"),
                            "inscrits": st.column_config.NumberColumn(
                                "Inscrits", format="%d"
                            ),
                            "rattachement_approx": st.column_config.CheckboxColumn(
                                "Rattachement approximatif",
                                help="Zone déduite du nom de la localité, faute de "
                                     "coordonnées fiables.",
                            ),
                        },
                    )
                    safe_code = re.sub(r"[^A-Za-z0-9_-]+", "_", str(code_clique))
                    st.download_button(
                        f"Exporter {nom_clique} (CSV)",
                        table.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"inscrits_{niveau.lower()}_{safe_code}.csv",
                        mime="text/csv",
                        icon=":material/download:",
                        key="export_zone",
                    )
    else:
        st.info(
            "Installez `folium` et `streamlit-folium` pour la carte détaillée.",
            icon=":material/info:",
        )
        fallback_points = pd.concat(
            ([etabs_zone[["lat", "lon"]]] if draw_etabs else [])
            + ([subs_points[["lat", "lon"]]] if draw_subs else [])
        ) if (draw_etabs or draw_subs) else pd.DataFrame(columns=["lat", "lon"])
        if len(fallback_points):
            st.map(fallback_points, size=200)

if vue == "Établissements":
    # --------------------------------- Tableau --------------------------------- #
    st.html(
        '<div class="section-title">Détail des établissements</div>'
        f'<div class="section-sub">{len(filtered)} ligne(s) — cliquez un en-tête '
        "pour trier.</div>"
    )

    if filtered.empty:
        st.info(
            "Aucun établissement ne correspond aux filtres actuels.",
            icon=":material/search_off:",
        )
    else:
        st.dataframe(
            filtered[["Province", "Établissement", "Catégorie", "lat", "lon"]],
            width="stretch",
            hide_index=True,
            column_config={
                "Province": st.column_config.TextColumn("Province / ville", width="medium"),
                "Établissement": st.column_config.TextColumn("Établissement", width="large"),
                "Catégorie": st.column_config.TextColumn("Catégorie", width="small"),
                "lat": st.column_config.NumberColumn("Latitude", format="%.6f"),
                "lon": st.column_config.NumberColumn("Longitude", format="%.6f"),
            },
        )

        st.download_button(
            "Exporter la sélection (CSV)",
            filtered.to_csv(index=False).encode("utf-8-sig"),
            file_name="etablissements.csv",
            mime="text/csv",
            icon=":material/download:",
        )

    if not unlocated.empty:
        with st.expander(
            f"{len(unlocated)} établissement(s) sans coordonnées exploitables",
            icon=":material/wrong_location:",
        ):
            st.caption(
                "Ces lignes n'apparaissent pas sur la carte : la cellule de "
                "coordonnées du Sheet n'est pas au format « latitude, longitude »."
            )
            st.dataframe(
                unlocated[["Province", "Établissement", "Catégorie", "Coordonnées brutes"]],
                width="stretch",
                hide_index=True,
            )

if vue == "Pré-inscrits":
    # --------------------- Récapitulatif des pré-souscripteurs ------------------ #
    if has_subscribers:
        st.html(
            '<div class="section-title">Pré-souscripteurs eAriary</div>'
            f'<div class="section-sub">{len(subs_points)} localité(s) — le fichier '
            "d'inscription ne contient pas de coordonnées : les adresses sont "
            "géocodées puis agrégées, sans donnée nominative.</div>"
        )

        if subs_points.empty:
            st.info(
                "Aucun pré-souscripteur géolocalisé ne correspond aux filtres.",
                icon=":material/search_off:",
            )
        else:
            recap_cols = ["Localité", "Ville", "Région", "Inscrits"] + [
                a for a in ACCOUNT_ORDER + ["Non renseigné"] if subs_points[a].sum()
            ]
            recap = subs_points[recap_cols]
            st.dataframe(
                recap,
                width="stretch",
                hide_index=True,
                column_config={
                    "Localité": st.column_config.TextColumn("Localité", width="medium"),
                    "Ville": st.column_config.TextColumn("Ville", width="medium"),
                    "Région": st.column_config.TextColumn("Région", width="medium"),
                    "Inscrits": st.column_config.ProgressColumn(
                        "Inscrits",
                        format="%d",
                        min_value=0,
                        max_value=int(subs_points["Inscrits"].max()),
                    ),
                },
            )
            st.download_button(
                "Exporter le récapitulatif (CSV)",
                recap.to_csv(index=False).encode("utf-8-sig"),
                file_name="pre_souscripteurs_par_localite.csv",
                mime="text/csv",
                icon=":material/download:",
            )

        sub_unlocated = subs_filtered[subs_filtered["lat"].isna()]
        if not sub_unlocated.empty:
            with st.expander(
                f"{len(sub_unlocated)} pré-souscripteur(s) sans adresse localisable",
                icon=":material/wrong_location:",
            ):
                st.caption(
                    "Ces inscriptions n'apparaissent pas sur la carte : soit le "
                    "géocodeur n'a reconnu aucun niveau de l'adresse (introuvable), "
                    "soit celle-ci a été saisie sans ville ni région et le point "
                    "obtenu n'est pas fiable (incertaine)."
                )
                st.dataframe(
                    sub_unlocated.groupby(["Adresse", "precision"])
                    .size()
                    .reset_index(name="Inscrits")
                    .sort_values("Inscrits", ascending=False),
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Adresse": st.column_config.TextColumn("Adresse", width="large"),
                        "precision": st.column_config.TextColumn("Motif", width="small"),
                    },
                )

    # ------------------ Import de la liste des pré-inscrits -------------------- #
    # Le seul endroit de l'application qui écrit sur le disque, et le seul qui
    # accède au réseau au runtime — le géocodage était jusqu'ici réservé au script
    # de `tools/`. Les deux sont contenus dans le bouton d'import : rien ne part et
    # rien ne s'écrit tant qu'il n'a pas été pressé.
    st.html(
        '<div class="section-title">Importer la liste des pré-inscrits</div>'
        '<div class="section-sub">Déposez l\'export des inscriptions (CSV ou Excel) : '
        "les adresses sont uniformisées, les nouvelles géocodées, et la carte se met "
        "à jour. Seuls les effectifs par adresse et par type de compte sont "
        "conservés — ni nom, ni téléphone, ni e-mail ne quitte cette page.</div>"
    )

    # Bilan du dernier import, déposé avant le rechargement de la page : le message
    # doit survivre au `st.rerun()` qui suit l'écriture des fichiers.
    if bilan := st.session_state.pop("import_bilan", None):
        st.success(bilan, icon=":material/task_alt:")

    fichier_importe = st.file_uploader(
        "Fichier des pré-inscrits",
        type=["csv", "xlsx", "xls"],
        help="Colonnes attendues : une adresse et un type de compte. Les autres "
             "colonnes sont ignorées. Le séparateur et l'encodage sont détectés.",
    )


    @st.cache_data(show_spinner=False)
    def lire_import(contenu: bytes, nom: str):
        """Lecture du fichier déposé, mise en cache sur son contenu.

        Streamlit réexécute le script à chaque clic — sans ce cache, un fichier de
        plusieurs milliers de lignes serait relu à chaque case cochée.
        """
        return pre_inscrits.lire_fichier(contenu, nom)


    if fichier_importe is not None:
        try:
            brut = lire_import(fichier_importe.getvalue(), fichier_importe.name)
        except Exception as exc:
            brut = None
            st.error(f"Fichier illisible : {exc}", icon=":material/error:")

        if brut is not None and brut.empty:
            st.warning("Le fichier ne contient aucune ligne.", icon=":material/warning:")
        elif brut is not None:
            detectee_adresse, detectee_compte = pre_inscrits.colonnes_utiles(brut)
            colonnes = list(brut.columns)

            # Détection proposée, jamais imposée : un export dont les intitulés ont
            # changé se rattrape ici, sans toucher au code.
            choix_col = st.columns(2)
            col_adresse = choix_col[0].selectbox(
                "Colonne des adresses",
                colonnes,
                index=colonnes.index(detectee_adresse) if detectee_adresse in colonnes else 0,
            )
            col_compte = choix_col[1].selectbox(
                "Colonne du type de compte",
                ["— aucune —"] + colonnes,
                index=(colonnes.index(detectee_compte) + 1) if detectee_compte in colonnes else 0,
            )

            prepare = pre_inscrits.preparer(
                brut, col_adresse, None if col_compte == "— aucune —" else col_compte
            )
            correspondances = pre_inscrits.charger_correspondances()
            prepare["Adresse"] = pre_inscrits.appliquer_correspondances(
                prepare["Adresse"], correspondances
            )

            cache_geo = pre_inscrits.charger_cache_geo()
            precisions = {a: v.get("precision", "") for a, v in cache_geo.items()}
            effectifs = pre_inscrits.effectifs_par_adresse(prepare)
            suggestions = pre_inscrits.suggerer_fusions(effectifs, precisions)

            # Les fusions cochées sont appliquées à blanc dès maintenant : le nombre
            # d'adresses à géocoder, donc la durée annoncée, doit refléter ce qui va
            # réellement être fait.
            retenues = {}
            for index, suggestion in enumerate(suggestions):
                if st.session_state.get(f"fusion_{index}"):
                    for variante in suggestion["variantes"]:
                        retenues[pre_inscrits.cle(variante)] = suggestion["retenue"]
            adresses_finales = pre_inscrits.appliquer_correspondances(
                prepare["Adresse"], retenues
            )
            a_geocoder = pre_inscrits.adresses_a_geocoder(adresses_finales.unique(), cache_geo)

            ancien = pre_inscrits.lire_agregat()
            ancien_total = (
                pd.to_numeric(ancien["Inscrits"], errors="coerce").fillna(0).sum()
                if not ancien.empty
                else 0
            )

            mesures = st.columns(4)
            mesures[0].metric(
                "Lignes lues",
                f"{len(prepare):,}".replace(",", " "),
                delta=f"{len(prepare) - int(ancien_total):+d} vs liste actuelle" if ancien_total else None,
                delta_color="off",
            )
            mesures[1].metric("Adresses distinctes", f"{adresses_finales.nunique()}")
            mesures[2].metric(
                "Libellés uniformisés",
                f"{int((prepare['Adresse importée'].str.strip() != prepare['Adresse']).sum())}",
                help="Lignes dont l'adresse a été réécrite : espaces, casse, alias de "
                     "ville, pays ajouté, e-mail neutralisé.",
            )
            mesures[3].metric(
                "Adresses à géocoder",
                f"{len(a_geocoder)}",
                help="Adresses absentes du cache. Nominatim impose une requête par "
                     "seconde : comptez environ autant de secondes.",
            )

            resume = pre_inscrits.resume_uniformisation(prepare)
            if not resume.empty:
                with st.expander(
                    f"{len(resume)} libellé(s) réécrit(s) par les règles",
                    icon=":material/rule:",
                ):
                    st.caption(
                        "Uniformisation automatique : espaces et virgules, casse des "
                        "saisies tout en capitales, noms de villes usuels ramenés au "
                        "nom officiel, « Madagascar » ajouté aux adresses qui portent "
                        "déjà une ville ou une région, adresses e-mail neutralisées."
                    )
                    st.dataframe(resume, width="stretch", hide_index=True)

            if suggestions:
                with st.expander(
                    f"{len(suggestions)} rapprochement(s) proposé(s) — à confirmer",
                    icon=":material/merge:",
                ):
                    st.caption(
                        "Ces libellés se ressemblent, mais rien ne dit qu'ils désignent "
                        "le même lieu : « Itaosy » et « Itasy » se ressemblent et sont "
                        "deux endroits différents. Rien n'est fusionné sans votre "
                        "accord ; une case cochée vaut pour tous les imports suivants."
                    )
                    for index, suggestion in enumerate(suggestions):
                        st.checkbox(
                            f"**{suggestion['retenue']}** ← "
                            + ", ".join(suggestion["variantes"])
                            + f"  ·  {suggestion['inscrits']} inscrit(s)  ·  "
                            + suggestion["motif"],
                            key=f"fusion_{index}",
                        )

            if a_geocoder:
                st.caption(
                    f"{len(a_geocoder)} adresse(s) seront géocodées auprès de "
                    f"Nominatim, à une requête par seconde — environ "
                    f"{max(1, round(len(a_geocoder) * pre_inscrits.PAUSE / 60))} minute(s). "
                    "C'est le seul accès réseau de l'application."
                )

            st.warning(
                "L'import **remplace** la liste actuelle "
                f"({int(ancien_total)} inscrit(s)) par celle du fichier déposé. "
                "Le cache de géocodage, lui, s'enrichit sans rien perdre.",
                icon=":material/warning:",
            )

            if st.button(
                "Importer et mettre à jour",
                icon=":material/publish:",
                type="primary",
            ):
                table = dict(correspondances)
                table.update(retenues)
                adresses = pre_inscrits.appliquer_correspondances(prepare["Adresse"], table)
                resultat = prepare.assign(Adresse=adresses)
                restants = pre_inscrits.adresses_a_geocoder(adresses.unique(), cache_geo)

                with st.status("Import en cours…", expanded=True) as etat:
                    if retenues:
                        st.write(f"Enregistrement de {len(retenues)} rapprochement(s).")
                    pre_inscrits.enregistrer_correspondances(table)

                    echecs = 0
                    if restants:
                        st.write(f"Géocodage de {len(restants)} nouvelle(s) adresse(s)…")
                        avancement = st.progress(0.0)
                        ligne = st.empty()
                        for rang, adresse in enumerate(restants, 1):
                            trouve = pre_inscrits.geocoder(adresse)
                            cache_geo[adresse] = {"Adresse": adresse, **trouve}
                            echecs += trouve["precision"] in ("introuvable", "erreur réseau")
                            # Écriture à chaque tour : une fermeture d'onglet en
                            # cours de route ne perd aucune résolution déjà payée.
                            pre_inscrits.enregistrer_cache_geo(cache_geo)
                            avancement.progress(rang / len(restants))
                            ligne.caption(f"[{rang}/{len(restants)}] {adresse} → {trouve['precision']}")
                        ligne.empty()

                    agregat = pre_inscrits.agreger(resultat)
                    pre_inscrits.enregistrer_agregat(agregat)
                    st.write(f"Agrégat écrit : {len(agregat)} ligne(s).")
                    etat.update(label="Import terminé", state="complete", expanded=False)

                st.session_state["import_bilan"] = (
                    f"{len(resultat)} inscription(s) importée(s), "
                    f"{adresses.nunique()} adresse(s) distincte(s), "
                    f"{len(restants)} géocodée(s)"
                    + (f", dont {echecs} sans résultat" if echecs else "")
                    + "."
                )
                # Le cache de `load_subscribers` porte sur 5 minutes : sans purge,
                # la carte afficherait encore l'ancienne liste.
                st.cache_data.clear()
                st.rerun()

if vue == "Intégration":
    # ----------------------- Pages publiques à intégrer ------------------------ #
    # Les pages vivent dans `partenaires/`, à la racine du dépôt, et sont publiées
    # par GitHub Pages. L'application n'en héberge aucune copie : il n'existe
    # qu'une seule version en ligne, et les adresses ci-dessous sont celles que
    # l'on donne aux intégrateurs — elles n'exigent aucune connexion,
    # contrairement à cette application.
    # Voir `partenaires/README.md` pour les paramètres d'URL et les messages.

    # Deux pages, même dossier : la carte, et le tableau filtrable par région et
    # par type de marchand. Hauteurs conseillées différentes — le tableau n'a pas
    # de carte à laisser respirer.
    EMBED_PAGES = [
        ("Carte", "carte.html", 620, "Carte et liste des établissements, filtres ville et catégorie."),
        (
            "Tableau",
            "tableau.html",
            520,
            "Registre triable, filtres région et type de marchand, lien Google Maps par ligne. "
            "Ni carte ni tuiles : c'est la page à préférer quand l'hôte n'a pas besoin d'une carte.",
        ),
    ]

    st.html(
        '<div class="section-title">Pages publiques à intégrer</div>'
        '<div class="section-sub">Établissements partenaires, destinés au public et '
        "à l'intégration dans une autre application. Ces pages ne montrent ni les "
        "pré-souscripteurs ni les indicateurs internes.</div>"
    )

    st.caption(
        "À intégrer sans bordure ni coin arrondi, pour que la page se lise comme "
        "une section de l'application hôte et non comme un encart rapporté. "
        "Ajoutez `?header=0` si l'hôte affiche déjà son propre titre."
    )

    for _titre, _fichier, _hauteur, _sous_titre in EMBED_PAGES:
        _url = f"{PAGES_PUBLIQUES}/{_fichier}"
        st.markdown(f"**{_titre}** — {_sous_titre}")
        st.link_button(
            f"Ouvrir la page « {_titre} »",
            _url,
            icon=":material/open_in_new:",
        )
        st.code(
            f'<iframe\n'
            f'  src="{_url}"\n'
            f'  title="Établissements partenaires eAriary"\n'
            f'  width="100%" height="{_hauteur}" style="display:block;border:0"\n'
            f'  loading="lazy"></iframe>',
            language="html",
        )
        with st.expander(f"Aperçu — {_titre}", icon=":material/preview:"):
            st.iframe(_url, height=_hauteur)
