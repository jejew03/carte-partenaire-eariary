"""
Carte des établissements — Madagascar
Lit les données depuis un Google Sheet public (export CSV) avec repli
sur une copie locale embarquée si le réseau ou le partage n'est pas disponible.

Lancement :  streamlit run app.py
"""

import io
import re
import unicodedata

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

# ------------------------------- Indicateurs ------------------------------- #
c1, c2, c3, c4 = st.columns(4, gap="medium")
c1.metric("Établissements", len(filtered), border=True)
c2.metric("Géolocalisés", len(filtered_located), border=True)
c3.metric("Sans coordonnées", len(filtered) - len(filtered_located), border=True)
c4.metric("Villes couvertes", filtered["Province"].nunique(), border=True)

# --------------------------------- Carte ----------------------------------- #
try:
    import folium
    from folium.plugins import MarkerCluster
    from streamlit_folium import st_folium

    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

if filtered_located.empty:
    st.html('<div class="section-title">Carte</div>')
    st.info(
        "Aucun établissement géolocalisé ne correspond aux filtres. "
        "Élargissez la sélection dans le panneau latéral pour afficher la carte.",
        icon=":material/filter_alt_off:",
    )
elif HAS_FOLIUM:
    st.html(
        '<div class="section-title">Carte</div>'
        f'<div class="section-sub">{len(filtered_located)} établissement(s) '
        "positionné(s). Cliquez un marqueur pour le détail.</div>"
    )

    # Légende avant la carte : lisible sans faire défiler, et chaque catégorie
    # porte son libellé — la couleur n'est jamais la seule information.
    legend_items = "".join(
        f'<span class="legend-item">'
        f'<span class="swatch" style="background:{CATEGORY_STYLE.get(c, DEFAULT_STYLE)[2]}"></span>'
        f"{c}</span>"
        for c in sort_fr(filtered_located["Catégorie"].unique())
    )
    st.html(f'<div class="legend">{legend_items}</div>')

    center = [filtered_located["lat"].mean(), filtered_located["lon"].mean()]
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

    if len(filtered_located) > 1:
        fmap.fit_bounds(filtered_located[["lat", "lon"]].values.tolist(), padding=(30, 30))

    folium.LayerControl(collapsed=True).add_to(fmap)
    st_folium(fmap, use_container_width=True, height=580, returned_objects=[])
else:
    st.info(
        "Installez `folium` et `streamlit-folium` pour la carte détaillée.",
        icon=":material/info:",
    )
    st.map(filtered_located[["lat", "lon"]], size=200)

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
        