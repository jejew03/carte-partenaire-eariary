"""
Carte des établissements — Madagascar
Lit les données depuis un Google Sheet public (export CSV) avec repli
sur une copie locale embarquée si le réseau ou le partage n'est pas disponible.

Superpose les pré-souscripteurs eAriary (fichier Excel local), agrégés par
localité : le fichier ne contient que des adresses textuelles, géocodées une
fois pour toutes par `tools/geocode_souscripteurs.py`.

Lancement :  streamlit run app.py
"""

import io
import re
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

SHEET_ID = "1D15egjrBB_9eNCXC-THxZcSqvNtf7ttfssdcVDRu8Yo"
GID = "0"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"

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
ACCOUNT_ORDER = ["Particulier", "Marchand", "Épicerie", "Grande Entreprise"]

# Le champ « Adresse » du fichier d'inscription contient parfois une adresse
# e-mail. Même règle que `tools/geocode_souscripteurs.py` : sans valeur
# géographique, et affichée telle quelle elle identifierait une personne.
EMAIL_LIKE = re.compile(
    r"@|(?:gmail|yahoo|hotmail|outlook|orange|moov|telma|esemahay)\.?(?:com|fr|mg)",
    re.IGNORECASE,
)
UNKNOWN_ADDRESS = "Adresse non renseignée"

# Font Awesome 6 ne rattache la police qu'aux classes .fas / .fa-solid, alors que
# leaflet-awesome-markers n'émet que .fa : sans ce correctif les marqueurs
# affichent un carré vide à la place de l'icône.
MAP_ICON_FIX = """
<style>
  .awesome-marker i.fa { font-family: "Font Awesome 6 Free"; font-weight: 900; }
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
    if SUBSCRIBERS_XLSX.exists():
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

      /* Titres de section plus calmes que le titre de page */
      .section-title {
        font-size: 1.05rem; font-weight: 600; color: #0F172A;
        margin: 2rem 0 .2rem;
      }
      .section-title + .section-sub {
        margin: 0 0 .75rem; color: #64748B; font-size: .875rem;
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
            help="Cercles proportionnels au nombre d'inscrits par localité.",
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

# ------------------------------- Indicateurs ------------------------------- #
c1, c2, c3, c4 = st.columns(4, gap="medium")
c1.metric("Établissements", len(filtered), border=True)
c2.metric("Géolocalisés", len(filtered_located), border=True)
c3.metric("Sans coordonnées", len(filtered) - len(filtered_located), border=True)
c4.metric("Villes couvertes", filtered["Province"].nunique(), border=True)

if has_subscribers:
    s1, s2, s3, s4 = st.columns(4, gap="medium")
    s1.metric("Pré-souscripteurs", len(subs_filtered), border=True)
    s2.metric("Positionnés", int(subs_points["Inscrits"].sum()), border=True)
    s3.metric("Localités", len(subs_points), border=True)
    s4.metric("Régions couvertes", subs_filtered["Région"].nunique(), border=True)

if sub_warning:
    st.warning(sub_warning, icon=":material/warning:")

# --------------------------------- Carte ----------------------------------- #
try:
    import folium
    from folium.plugins import MarkerCluster
    from streamlit_folium import st_folium

    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

draw_subs = bool(show_subs) and not subs_points.empty
map_empty = filtered_located.empty and not draw_subs

if map_empty:
    st.html('<div class="section-title">Carte</div>')
    st.info(
        "Aucun point à afficher avec les filtres actuels. "
        "Élargissez la sélection dans le panneau latéral pour afficher la carte.",
        icon=":material/filter_alt_off:",
    )
elif HAS_FOLIUM:
    counts = [f"{len(filtered_located)} établissement(s) positionné(s)"]
    if draw_subs:
        counts.append(
            f"{int(subs_points['Inscrits'].sum())} pré-souscripteur(s) "
            f"sur {len(subs_points)} localité(s)"
        )
    st.html(
        '<div class="section-title">Carte</div>'
        f'<div class="section-sub">{" — ".join(counts)}. Cliquez un marqueur '
        "ou un cercle pour le détail.</div>"
    )

    # Légende avant la carte : lisible sans faire défiler, et chaque catégorie
    # porte son libellé — la couleur n'est jamais la seule information.
    legend_items = "".join(
        f'<span class="legend-item">'
        f'<span class="swatch" style="background:{CATEGORY_STYLE.get(c, DEFAULT_STYLE)[2]}"></span>'
        f"{c}</span>"
        for c in sort_fr(filtered_located["Catégorie"].unique())
    )
    if draw_subs:
        legend_items += (
            f'<span class="legend-item">'
            f'<span class="swatch" style="background:{SUBSCRIBER_COLOR};'
            'opacity:.55;border:1px solid ' + SUBSCRIBER_COLOR + '"></span>'
            "Pré-souscripteurs (taille = nombre d'inscrits)</span>"
        )
    st.html(f'<div class="legend">{legend_items}</div>')

    all_points = pd.concat(
        [filtered_located[["lat", "lon"]]]
        + ([subs_points[["lat", "lon"]]] if draw_subs else [])
    )
    center = [all_points["lat"].mean(), all_points["lon"].mean()]
    fmap = folium.Map(location=center, zoom_start=6, tiles=None, control_scale=True)
    fmap.get_root().header.add_child(folium.Element(MAP_ICON_FIX))

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

    cluster = MarkerCluster(name="Établissements").add_to(fmap)

    for _, row in filtered_located.iterrows():
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

    folium.LayerControl(collapsed=True).add_to(fmap)
    st_folium(fmap, use_container_width=True, height=580, returned_objects=[])
else:
    st.info(
        "Installez `folium` et `streamlit-folium` pour la carte détaillée.",
        icon=":material/info:",
    )
    fallback_points = pd.concat(
        [filtered_located[["lat", "lon"]]]
        + ([subs_points[["lat", "lon"]]] if draw_subs else [])
    )
    st.map(fallback_points, size=200)

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
        