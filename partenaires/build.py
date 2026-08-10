#!/usr/bin/env python3
"""Régénère l'instantané des partenaires (`assets/instantane.js`).

Les deux pages relisent le Google Sheet en direct dans le navigateur, mais
elles doivent afficher quelque chose immédiatement — et rester utilisables si
le Sheet redevient privé, si le réseau tombe, ou si l'application hôte applique
une politique de sécurité qui interdit l'appel à docs.google.com. D'où cet
instantané, versionné avec le reste du dossier :

    python partenaires/build.py            # relit le Sheet et réécrit l'instantané
    python partenaires/build.py --check    # compare sans écrire (code 1 si différent)

En temps normal personne ne le lance à la main : le workflow
`.github/workflows/instantane-partenaires.yml` s'en charge toutes les heures.

Les règles de lecture — détection de l'en-tête, recherche des colonnes par
mots-clés, format des coordonnées, corrections de libellés — sont reproduites à
l'identique dans `assets/donnees.js`, qui relit le Sheet côté navigateur. Toute
évolution du Sheet doit donc se répercuter dans ces deux fichiers.

Stdlib uniquement : le script doit tourner sans le virtualenv du projet, et
notamment sur un runner GitHub nu.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SHEET_ID = "1D15egjrBB_9eNCXC-THxZcSqvNtf7ttfssdcVDRu8Yo"
GID = "0"
CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"
)

BASE_DIR = Path(__file__).resolve().parent
OUTPUT = BASE_DIR / "assets" / "instantane.js"
# Limites administratives déjà versionnées pour la choroplèthe de l'application
# interne : c'est d'elles qu'on déduit la région de chaque point.
ADM1 = BASE_DIR.parent / "data" / "geo" / "mdg_adm1.geojson"

# « -12.289942, 49.291381 » — antislashs et virgules décimales tolérés. Une
# cellule qui ne correspond pas (« Introuvable, quartier Amparihy ») laisse
# l'établissement dans la liste, sans point sur la carte.
COORD_RE = re.compile(
    r"^\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*[,;]\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*$"
)

# Colonnes attendues. Chaque entrée : (clé, mots-clés d'en-tête, position de
# repli). Le repli n'est utilisé que si aucun mot-clé ne correspond ; une
# colonne trouvée en position 0 doit être retenue telle quelle, d'où un indice
# explicite plutôt qu'un `or`.
COLONNES = (
    ("province", ("province", "ville", "région", "region"), 0),
    ("nom", ("établissement", "etablissement", "enseigne", "nom"), 1),
    ("categorie", ("catégorie", "categorie", "type"), 2),
    ("coordonnees", ("latitude", "longitude", "coord", "gps"), 3),
)

# Colonnes facultatives : elles n'existent pas encore dans le Sheet. Le jour où
# l'une d'elles y est ajoutée, elle apparaît d'elle-même dans les pages, sans
# que rien n'ait à être touché ici. Tant qu'aucune ligne n'est remplie, le
# champ reste absent de l'instantané et les pages ne changent pas d'aspect.
#
# Aucun repli de position : une colonne facultative n'existe que si son
# intitulé la nomme. Deviner sa place ferait passer une colonne quelconque pour
# un numéro de téléphone.
OPTIONNELLES = (
    ("telephone", ("téléphone", "telephone", "tel.", "tél.", "phone", "mobile",
                   "whatsapp", "contact")),
    ("adresse", ("adresse", "address", "quartier", "rue", "lot ")),
    ("horaires", ("horaire", "ouverture", "ouvert", "heures", "hours")),
    ("site", ("site", "web", "url", "facebook", "lien", "page")),
)

# Fautes de frappe récurrentes du Sheet. Les catégories sont celles de
# `app.py` ; les provinces s'y ajoutent parce que ces pages s'adressent au
# public, où « Antsirananana » se remarque. Le mieux reste de corriger le Sheet
# puis de vider ces deux tables — ici et dans `assets/donnees.js`.
CATEGORY_FIXES = {
    "Supermaché": "Supermarché",
    "Supermarche": "Supermarché",
    "Epicerie": "Épicerie",
    "Hotel": "Hôtel",
}
PROVINCE_FIXES = {
    "Antsirananana": "Antsiranana",
    "Fianaratsoa": "Fianarantsoa",
}
EMPTY_LABEL = "Non renseignée"


def fetch_csv(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "eariary-partenaires/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def plier(texte: str) -> str:
    """Minuscules sans accents : « Téléphone » et « telephone » se valent."""
    sans_accent = unicodedata.normalize("NFD", str(texte))
    return "".join(c for c in sans_accent if not unicodedata.combining(c)).lower()


def find_header(rows: list[list[str]]) -> int:
    """Indice de la ligne d'en-tête : la première qui nomme une colonne connue.

    Le Sheet commence parfois par un titre ou une ligne vide. On cherche le mot
    « province » — présent depuis toujours — puis, à défaut, « établissement » :
    une future feuille pourrait renommer la première colonne « Ville ».
    """
    for index, row in enumerate(rows[:10]):
        ligne = plier(" ".join(row))
        if "province" in ligne or "etablissement" in ligne:
            return index
    return 0


def find_col(
    header: list[str], keywords: tuple[str, ...], default: int | None, pris: set[int]
) -> int | None:
    """Indice de la première colonne libre dont l'intitulé porte un mot-clé.

    `pris` évite qu'une colonne déjà attribuée soit reprise par un champ
    facultatif : « Latitude / longitude » est la colonne des coordonnées, pas
    celle de l'adresse, même si un jour un mot-clé les rapprochait.
    """
    for index, cell in enumerate(header):
        if index in pris:
            continue
        bas = plier(cell)
        if any(plier(keyword) in bas for keyword in keywords):
            return index
    return default


def parse_coords(value: str) -> tuple[float | None, float | None]:
    match = COORD_RE.match(value.replace("\\", "").strip())
    if not match:
        return None, None
    lat = float(match.group(1).replace(",", "."))
    lon = float(match.group(2).replace(",", "."))
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None, None
    return lat, lon


def capitalize_fr(value: str) -> str:
    """Première lettre haute, le reste bas — comme `str.capitalize()` côté pandas."""
    return value[:1].upper() + value[1:].lower() if value else value


def parse_rows(text: str) -> tuple[list[dict], list[str]]:
    """`(fiches, champs facultatifs réellement remplis)`."""
    rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text))]
    rows = [row for row in rows if any(row)]
    if not rows:
        raise ValueError("feuille vide")

    header_index = find_header(rows)
    header = rows[header_index]
    body = rows[header_index + 1 :]

    pris: set[int] = set()
    index_de: dict[str, int | None] = {}
    for cle, mots, defaut in COLONNES:
        position = find_col(header, mots, defaut, pris)
        index_de[cle] = position
        if position is not None:
            pris.add(position)
    for cle, mots in OPTIONNELLES:
        position = find_col(header, mots, None, pris)
        index_de[cle] = position
        if position is not None:
            pris.add(position)

    def cell(row: list[str], index: int | None) -> str:
        if index is None or index >= len(row):
            return ""
        return row[index]

    etablissements = []
    for row in body:
        nom = cell(row, index_de["nom"])
        if not nom or nom.lower() in {"nan", "none"}:
            continue

        categorie = capitalize_fr(cell(row, index_de["categorie"]))
        categorie = CATEGORY_FIXES.get(categorie, categorie) or EMPTY_LABEL
        province = cell(row, index_de["province"])
        province = PROVINCE_FIXES.get(province, province) or EMPTY_LABEL
        brut = cell(row, index_de["coordonnees"])
        lat, lon = parse_coords(brut)

        fiche = {
            "nom": nom,
            "categorie": categorie,
            "province": province,
            "lat": lat,
            "lon": lon,
            "coordonnees_brutes": brut,
        }
        for cle, _ in OPTIONNELLES:
            valeur = cell(row, index_de[cle])
            if valeur:
                fiche[cle] = valeur
        etablissements.append(fiche)

    # Une colonne présente mais entièrement vide ne compte pas : elle ferait
    # apparaître une colonne « Contact » sans un seul numéro.
    champs = [
        cle
        for cle, _ in OPTIONNELLES
        if any(fiche.get(cle) for fiche in etablissements)
    ]
    return etablissements, champs


# --------------------------------------------------------------------------- #
# Région administrative
# --------------------------------------------------------------------------- #
# Le Sheet ne porte pas la région : sa colonne « Province » mélange villes
# (Tolagnaro, Sambava) et anciennes provinces (Mahajanga, Toamasina). La région
# est donc déduite des coordonnées, par appartenance au polygone ADM1 — les
# mêmes limites que la choroplèthe de l'application interne, déjà dans le
# dépôt. Aucun accès réseau, stdlib uniquement : pas de geopandas ici.

# Un point peut tomber hors de tout polygone — trait de côte simplifié à
# ~880 m, saisie GPS approximative. Il rejoint alors la région la plus proche,
# dans cette limite (en degrés, ~28 km) ; au-delà, la coordonnée est trop
# douteuse pour qu'on lui attribue une région.
RATTACHEMENT_MAX_DEG = 0.25


def _polygones(geometrie: dict) -> list:
    """Liste de polygones ; chacun est une liste d'anneaux (extérieur, trous)."""
    coordonnees = geometrie.get("coordinates") or []
    if geometrie.get("type") == "Polygon":
        return [coordonnees]
    if geometrie.get("type") == "MultiPolygon":
        return list(coordonnees)
    return []


def charger_regions(chemin: Path = ADM1) -> list[tuple[str, tuple, list]]:
    """`[(nom, rectangle englobant, polygones)]` — liste vide si le fichier manque.

    Son absence n'est pas une erreur : l'instantané se génère alors sans région
    et le tableau affiche « Région à préciser ».
    """
    if not chemin.exists():
        return []

    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    regions = []
    for entite in donnees.get("features", []):
        proprietes = entite.get("properties") or {}
        nom = proprietes.get("nom_zone") or proprietes.get("ADM1_FR")
        polygones = _polygones(entite.get("geometry") or {})
        if not nom or not polygones:
            continue
        sommets = [
            point for polygone in polygones for anneau in polygone for point in anneau
        ]
        lons = [point[0] for point in sommets]
        lats = [point[1] for point in sommets]
        regions.append((nom, (min(lons), min(lats), max(lons), max(lats)), polygones))
    return regions


def _dans_anneau(lon: float, lat: float, anneau: list) -> bool:
    """Lancer de rayon : compte les intersections d'une demi-droite horizontale."""
    dedans = False
    precedent = len(anneau) - 1
    for courant in range(len(anneau)):
        x_i, y_i = anneau[courant][0], anneau[courant][1]
        x_j, y_j = anneau[precedent][0], anneau[precedent][1]
        # Le test d'encadrement garantit y_j != y_i : pas de division par zéro.
        if (y_i > lat) != (y_j > lat):
            if lon < x_i + (lat - y_i) * (x_j - x_i) / (y_j - y_i):
                dedans = not dedans
        precedent = courant
    return dedans


def _dans_polygone(lon: float, lat: float, polygone: list) -> bool:
    if not polygone or not _dans_anneau(lon, lat, polygone[0]):
        return False
    return not any(_dans_anneau(lon, lat, trou) for trou in polygone[1:])


def _distance_segment(lon: float, lat: float, a: list, b: list) -> float:
    """Distance du point au segment [a, b], en degrés.

    Les longitudes sont ramenées à l'échelle du parallèle : à Madagascar, un
    degré de longitude vaut environ 0,95 degré de latitude. Au segment et non
    au sommet le plus proche : une côte simplifiée peut n'avoir qu'un sommet
    tous les 900 m, et un point tombé juste au large serait sinon jugé lointain.
    """
    facteur = math.cos(math.radians(lat))
    x, y = lon * facteur, lat
    ax, ay = a[0] * facteur, a[1]
    bx, by = b[0] * facteur, b[1]
    dx, dy = bx - ax, by - ay
    longueur = dx * dx + dy * dy
    if longueur == 0:
        return math.hypot(x - ax, y - ay)
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / longueur))
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy))


def _distance_rectangle(lon: float, lat: float, rectangle: tuple) -> float:
    """Distance au rectangle englobant — nulle à l'intérieur. Filtre bon marché."""
    min_lon, min_lat, max_lon, max_lat = rectangle
    dx = max(min_lon - lon, 0.0, lon - max_lon) * math.cos(math.radians(lat))
    dy = max(min_lat - lat, 0.0, lat - max_lat)
    return math.hypot(dx, dy)


def region_de(lat: float | None, lon: float | None, regions: list) -> str:
    """Nom de la région contenant le point, ou de la plus proche ; sinon `""`."""
    if lat is None or lon is None or not regions:
        return ""

    for nom, rectangle, polygones in regions:
        min_lon, min_lat, max_lon, max_lat = rectangle
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            continue
        if any(_dans_polygone(lon, lat, polygone) for polygone in polygones):
            return nom

    # Aucune région ne le contient : au plus proche bord, tous anneaux
    # confondus — un point tombé dans un lac rejoint la région qui l'entoure.
    meilleure, distance_min = "", RATTACHEMENT_MAX_DEG
    for nom, rectangle, polygones in regions:
        if _distance_rectangle(lon, lat, rectangle) >= distance_min:
            continue
        for polygone in polygones:
            for anneau in polygone:
                for index in range(len(anneau) - 1):
                    distance = _distance_segment(
                        lon, lat, anneau[index], anneau[index + 1]
                    )
                    if distance < distance_min:
                        meilleure, distance_min = nom, distance
    return meilleure


def ajouter_regions(etablissements: list[dict], regions: list) -> int:
    """Complète chaque fiche par sa région. Renvoie le nombre de rattachements."""
    trouvees = 0
    for etablissement in etablissements:
        nom = region_de(etablissement["lat"], etablissement["lon"], regions)
        etablissement["region"] = nom
        trouvees += bool(nom)
    return trouvees


def regions_par_ville(etablissements: list[dict]) -> dict[str, str]:
    """Table ville → région, pour les lignes relues en direct dans le navigateur.

    Le navigateur n'a ni les polygones ni de quoi les parcourir : il rattache
    donc par le libellé de la colonne « Province », que cette table traduit.
    Une ville à cheval sur deux régions — cas non observé — prendrait la plus
    fréquente ; les coordonnées, elles, restent la référence dans l'instantané.
    """
    comptes: dict[str, Counter] = {}
    for etablissement in etablissements:
        if etablissement.get("region"):
            ville = etablissement["province"]
            comptes.setdefault(ville, Counter())[etablissement["region"]] += 1
    return {ville: compte.most_common(1)[0][0] for ville, compte in sorted(comptes.items())}


def completer_par_ville(
    etablissements: list[dict], villes_regions: dict[str, str]
) -> int:
    """Rattache par la ville les fiches qu'aucune coordonnée ne situe.

    Un établissement dont la cellule de coordonnées est inexploitable
    (« Introuvable, quartier Amparihy ») reste dans la liste ; il hérite de la
    région de sa ville plutôt que de rester sans région.
    """
    complets = 0
    for etablissement in etablissements:
        if not etablissement.get("region"):
            etablissement["region"] = villes_regions.get(etablissement["province"], "")
            complets += bool(etablissement["region"])
    return complets


# --------------------------------------------------------------------------- #
# Écriture
# --------------------------------------------------------------------------- #


def render(
    etablissements: list[dict],
    genere_le: str,
    villes_regions: dict[str, str],
    champs: list[str],
) -> str:
    payload = {
        "genere_le": genere_le,
        "champs": champs,
        "regions_par_ville": villes_regions,
        "etablissements": etablissements,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        "/* Instantané du registre des partenaires eAriary.\n"
        " *\n"
        " * Fichier généré — ne pas modifier à la main :\n"
        " *     python partenaires/build.py\n"
        " *\n"
        " * Régénéré toutes les heures par\n"
        " * .github/workflows/instantane-partenaires.yml. Les pages l'affichent\n"
        " * immédiatement, puis relisent le Google Sheet et remplacent ces\n"
        " * données dès qu'il répond. */\n"
        f"window.EARIARY_PARTENAIRES = {body};\n"
    )


def strip_timestamp(text: str) -> str:
    """Contenu hors date de génération, pour comparer deux instantanés."""
    return re.sub(r'"genere_le": "[^"]*"', '"genere_le": ""', text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="n'écrit rien ; code de sortie 1 si l'instantané n'est plus à jour",
    )
    args = parser.parse_args()

    try:
        text = fetch_csv(CSV_URL)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # L'instantané existant reste la meilleure donnée disponible : on ne
        # l'écrase pas avec une lecture ratée.
        print(f"Lecture du Sheet impossible : {exc}", file=sys.stderr)
        if OUTPUT.exists():
            print(f"{OUTPUT.name} laissé inchangé.", file=sys.stderr)
        return 1

    etablissements, champs = parse_rows(text)
    if not etablissements:
        print("Aucun établissement lisible dans le Sheet.", file=sys.stderr)
        return 1

    regions = charger_regions()
    if not regions:
        print(f"{ADM1.name} introuvable : instantané généré sans région.", file=sys.stderr)
    situes = ajouter_regions(etablissements, regions)
    villes_regions = regions_par_ville(etablissements)
    situes += completer_par_ville(etablissements, villes_regions)

    genere_le = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    contenu = render(etablissements, genere_le, villes_regions, champs)
    localises = sum(1 for e in etablissements if e["lat"] is not None)

    if args.check:
        ancien = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if strip_timestamp(ancien) == strip_timestamp(contenu):
            print(f"{OUTPUT.name} est à jour ({len(etablissements)} établissements).")
            return 0
        print(f"{OUTPUT.name} diffère du Sheet — relancez sans --check.")
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(contenu, encoding="utf-8")
    print(
        f"{OUTPUT.relative_to(BASE_DIR.parent)} : {len(etablissements)} établissements, "
        f"{localises} localisés, {situes} rattachés à une région "
        f"({len(villes_regions)} villes)"
        + (f", champs facultatifs : {', '.join(champs)}" if champs else "")
        + "."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
