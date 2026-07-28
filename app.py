"""
Carte des établissements — Madagascar
Lit les données depuis un Google Sheet public (export CSV) avec repli
sur une copie locale embarquée si le réseau ou le partage n'est pas disponible.

Lancement :  streamlit run app.py
"""

import io
import re

import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

SHEET_ID = "1D15egjrBB_9eNCXC-THxZcSqvNtf7ttfssdcVDRu8Yo"
GID = "0"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"

# Couleurs Folium disponibles : red, blue, green, purple, orange, darkred,
# lightred, beige, darkblue, darkgreen, cadetblue, darkpurple, pink, gray, black
CATEGORY_STYLE = {
    "Restaurant": ("red", "cutlery"),
    "Hôtel": ("blue", "bed"),
    "Boutique": ("green", "shopping-bag"),
    "Épicerie": ("orange", "shopping-basket"),
    "Magasin": ("purple", "shopping-cart"),
    "Supermarché": ("darkred", "shopping-cart"),
}
DEFAULT_STYLE = ("gray", "map-marker")

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

st.set_page_config(page_title="Carte des établissements", page_icon="📍", layout="wide")

st.title("📍 Carte des établissements — Madagascar")

data, source = load_data()
located = data.dropna(subset=["lat", "lon"])
unlocated = data[data["lat"].isna()]

# ------------------------------- Filtres ---------------------------------- #
with st.sidebar:
    st.header("Filtres")

    provinces = sorted(data["Province"].unique())
    sel_prov = st.multiselect("Province / ville", provinces, default=provinces,
                              placeholder="Toutes les villes")

    categories = sorted(data["Catégorie"].unique())
    sel_cat = st.multiselect("Catégorie", categories, default=categories,
                             placeholder="Toutes les catégories")

    query = st.text_input("Recherche par nom", "").strip().lower()

    st.divider()
    st.caption(f"Source : {source}")
    if st.button("🔄 Recharger les données"):
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
c1, c2, c3, c4 = st.columns(4)
c1.metric("Établissements affichés", len(filtered))
c2.metric("Géolocalisés", len(filtered_located))
c3.metric("Sans coordonnées", len(filtered) - len(filtered_located))
c4.metric("Provinces / villes", filtered["Province"].nunique())

# --------------------------------- Carte ----------------------------------- #
try:
    import folium
    from folium.plugins import MarkerCluster
    from streamlit_folium import st_folium

    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

if filtered_located.empty:
    st.warning("Aucun établissement géolocalisé ne correspond aux filtres.")
elif HAS_FOLIUM:
    center = [filtered_located["lat"].mean(), filtered_located["lon"].mean()]
    fmap = folium.Map(location=center, zoom_start=6, tiles="OpenStreetMap")

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satellite",
    ).add_to(fmap)

    cluster = MarkerCluster(name="Établissements").add_to(fmap)

    for _, row in filtered_located.iterrows():
        color, icon = CATEGORY_STYLE.get(row["Catégorie"], DEFAULT_STYLE)
        popup_html = f"""
            <div style="font-family:sans-serif;min-width:200px">
              <b style="font-size:14px">{row['Établissement']}</b><br>
              <span style="color:#666">{row['Catégorie']}</span><br>
              📍 {row['Province']}<br>
              <code style="font-size:11px">{row['lat']:.6f}, {row['lon']:.6f}</code><br>
              <a href="https://www.google.com/maps?q={row['lat']},{row['lon']}"
                 target="_blank">Ouvrir dans Google Maps ↗</a>
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

    folium.LayerControl().add_to(fmap)
    st_folium(fmap, use_container_width=True, height=600, returned_objects=[])

    # Légende
    legend = " &nbsp;•&nbsp; ".join(
        f"<span style='color:{CATEGORY_STYLE.get(c, DEFAULT_STYLE)[0]}'>●</span> {c}"
        for c in sorted(filtered_located["Catégorie"].unique())
    )
    st.markdown(f"<div style='font-size:13px'>{legend}</div>", unsafe_allow_html=True)
else:
    st.info("Installez `folium` et `streamlit-folium` pour la carte détaillée.")
    st.map(filtered_located[["lat", "lon"]], size=200)

# --------------------------------- Tableau --------------------------------- #
st.subheader("Détail des établissements")
st.dataframe(
    filtered[["Province", "Établissement", "Catégorie", "lat", "lon"]],
    use_container_width=True,
    hide_index=True,
    column_config={
        "lat": st.column_config.NumberColumn("Latitude", format="%.6f"),
        "lon": st.column_config.NumberColumn("Longitude", format="%.6f"),
    },
)

st.download_button(
    "⬇️ Exporter la sélection (CSV)",
    filtered.to_csv(index=False).encode("utf-8-sig"),
    file_name="etablissements.csv",
    mime="text/csv",
)

if not unlocated.empty:
    with st.expander(f"⚠️ {len(unlocated)} établissement(s) sans coordonnées exploitables"):
        st.dataframe(
            unlocated[["Province", "Établissement", "Catégorie", "Coordonnées brutes"]],
            use_container_width=True,
            hide_index=True,
        )