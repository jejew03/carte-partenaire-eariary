#!/usr/bin/env python3
"""Génère l'instantané des partenaires : assets/instantane.js.

    python3 partenaires/build.py            # relit le Sheet et réécrit le fichier
    python3 partenaires/build.py --check    # ne réécrit rien ; code 1 si périmé

L'instantané est la copie de secours affichée par carte.html et tableau.html
avant que le réseau réponde, et conservée si la relecture du Sheet échoue.
Le workflow .github/workflows/instantane-partenaires.yml le régénère chaque
heure ; il n'y a donc normalement pas à lancer ce script à la main.

Attention : assets/donnees.js applique EXACTEMENT les mêmes règles de lecture
(en-tête, colonnes, coordonnées, corrections de libellés) pour la relecture
côté navigateur. Toute modification ici doit être reportée là-bas.

Bibliothèque standard uniquement : aucune installation n'est nécessaire.
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

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

SHEET_ID = "1D15egjrBB_9eNCXC-THxZcSqvNtf7ttfssdcVDRu8Yo"
GID = "0"
CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"
)

BASE_DIR = Path(__file__).resolve().parent
OUTPUT = BASE_DIR / "assets" / "instantane.js"

# Limites administratives régionales, utilisées pour déduire la région de
# chaque point (voir la section « Région administrative » plus bas).
ADM1 = BASE_DIR.parent / "data" / "geo" / "mdg_adm1.geojson"

# Format accepté : « -12.289942, 49.291381 ». Les antislashs parasites et les
# virgules décimales sont tolérés. Une cellule non conforme laisse
# l'établissement dans la liste, sans coordonnées.
COORD_RE = re.compile(
    r"^\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*[,;]\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*$"
)

# Colonnes obligatoires : (clé, mots-clés cherchés dans l'en-tête, position de
# repli). La position de repli ne sert que si aucun mot-clé ne correspond.
COLONNES = (
    ("province", ("province", "ville", "région", "region"), 0),
    ("nom", ("établissement", "etablissement", "enseigne", "nom"), 1),
    ("categorie", ("catégorie", "categorie", "type"), 2),
    ("coordonnees", ("latitude", "longitude", "coord", "gps"), 3),
)

# Colonnes facultatives : absentes du Sheet aujourd'hui, prises en compte
# automatiquement le jour où elles y sont ajoutées. Pas de position de repli :
# une colonne facultative n'est reconnue que par son intitulé, pour ne pas
# présenter une colonne quelconque comme un numéro de téléphone.
OPTIONNELLES = (
    ("telephone", ("téléphone", "telephone", "tel.", "tél.", "phone", "mobile",
                   "whatsapp", "contact")),
    ("adresse", ("adresse", "address", "quartier", "rue")),
    ("horaires", ("horaire", "ouverture", "ouvert", "heures", "hours")),
    ("site", ("site", "web", "url", "facebook", "lien", "page")),
)

# Fautes de frappe présentes dans le Sheet. À supprimer d'ici ET de
# assets/donnees.js une fois le Sheet corrigé.
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


# --------------------------------------------------------------------------- #
# Lecture du Google Sheet
# --------------------------------------------------------------------------- #


def fetch_csv(url: str, timeout: int = 30) -> str:
    """Télécharge la feuille au format CSV."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "eariary-partenaires/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def plier(texte: str) -> str:
    """Minuscules sans accents, pour comparer les intitulés de colonnes."""
    sans_accent = unicodedata.normalize("NFD", str(texte))
    return "".join(c for c in sans_accent if not unicodedata.combining(c)).lower()


def find_header(rows: list[list[str]]) -> int:
    """Indice de la ligne d'en-tête.

    La feuille peut commencer par un titre ou des lignes vides : on retient la
    première ligne qui contient « province » ou « établissement ».
    """
    for index, row in enumerate(rows[:10]):
        ligne = plier(" ".join(row))
        if "province" in ligne or "etablissement" in ligne:
            return index
    return 0


def find_col(
    header: list[str], keywords: tuple[str, ...], default: int | None, pris: set[int]
) -> int | None:
    """Indice de la première colonne libre dont l'intitulé contient un mot-clé.

    `pris` contient les colonnes déjà attribuées, pour qu'une même colonne ne
    soit pas réutilisée par un second champ.
    """
    for index, cell in enumerate(header):
        if index in pris:
            continue
        bas = plier(cell)
        if any(plier(keyword) in bas for keyword in keywords):
            return index
    return default


def parse_coords(value: str) -> tuple[float | None, float | None]:
    """(latitude, longitude) ou (None, None) si la cellule est inexploitable."""
    match = COORD_RE.match(value.replace("\\", "").strip())
    if not match:
        return None, None
    lat = float(match.group(1).replace(",", "."))
    lon = float(match.group(2).replace(",", "."))
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None, None
    return lat, lon


def capitalize_fr(value: str) -> str:
    """Première lettre en majuscule, le reste en minuscules."""
    return value[:1].upper() + value[1:].lower() if value else value


def parse_rows(text: str) -> tuple[list[dict], list[str]]:
    """Convertit le CSV en fiches.

    Retourne (liste de fiches, liste des champs facultatifs réellement remplis).
    """
    rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text))]
    rows = [row for row in rows if any(row)]
    if not rows:
        raise ValueError("feuille vide")

    header_index = find_header(rows)
    header = rows[header_index]
    body = rows[header_index + 1 :]

    # Attribution des colonnes : les obligatoires d'abord, les facultatives
    # ensuite sur ce qu'il reste.
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
        # Champ facultatif vide = champ absent de la fiche.
        for cle, _ in OPTIONNELLES:
            valeur = cell(row, index_de[cle])
            if valeur:
                fiche[cle] = valeur
        etablissements.append(fiche)

    # Une colonne présente mais entièrement vide n'est pas signalée aux pages :
    # elle ferait apparaître une colonne « Contact » sans aucun numéro.
    champs = [
        cle
        for cle, _ in OPTIONNELLES
        if any(fiche.get(cle) for fiche in etablissements)
    ]
    return etablissements, champs


# --------------------------------------------------------------------------- #
# Région administrative
# --------------------------------------------------------------------------- #
# Le Sheet ne contient pas la région : sa colonne « Province » mélange des
# villes (Tolagnaro, Sambava) et d'anciennes provinces (Mahajanga, Toamasina).
# La région est donc déterminée ici, en testant l'appartenance de chaque point
# aux polygones du fichier ADM1. Le calcul est fait dans ce script, pas dans le
# navigateur : les polygones pèsent plusieurs mégaoctets.
#
# L'implémentation n'utilise que la bibliothèque standard (pas de geopandas),
# pour que le workflow GitHub tourne sans installer de dépendances.

# Distance maximale de rattachement, en degrés (~28 km), pour un point qui ne
# tombe dans aucun polygone : trait de côte simplifié, saisie GPS approximative.
RATTACHEMENT_MAX_DEG = 0.25


def _polygones(geometrie: dict) -> list:
    """Liste de polygones ; chaque polygone est une liste d'anneaux."""
    coordonnees = geometrie.get("coordinates") or []
    if geometrie.get("type") == "Polygon":
        return [coordonnees]
    if geometrie.get("type") == "MultiPolygon":
        return list(coordonnees)
    return []


def charger_regions(chemin: Path = ADM1) -> list[tuple[str, tuple, list]]:
    """Charge les régions : [(nom, rectangle englobant, polygones)].

    Retourne une liste vide si le fichier est absent : le script continue alors
    sans région, et les pages affichent « Région à préciser ».
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
    """Point dans un anneau ? Algorithme du lancer de rayon."""
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
    """Point dans le contour extérieur et hors de tous les trous ?"""
    if not polygone or not _dans_anneau(lon, lat, polygone[0]):
        return False
    return not any(_dans_anneau(lon, lat, trou) for trou in polygone[1:])


def _distance_segment(lon: float, lat: float, a: list, b: list) -> float:
    """Distance du point au segment [a, b], en degrés.

    Les longitudes sont multipliées par cos(latitude) pour compenser le
    resserrement des méridiens.
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
    """Distance au rectangle englobant (0 à l'intérieur) : filtre rapide."""
    min_lon, min_lat, max_lon, max_lat = rectangle
    dx = max(min_lon - lon, 0.0, lon - max_lon) * math.cos(math.radians(lat))
    dy = max(min_lat - lat, 0.0, lat - max_lat)
    return math.hypot(dx, dy)


def region_de(lat: float | None, lon: float | None, regions: list) -> str:
    """Région contenant le point ; à défaut la plus proche ; sinon "".

    Le rectangle englobant sert de filtre avant le test polygonal, qui est
    coûteux.
    """
    if lat is None or lon is None or not regions:
        return ""

    for nom, rectangle, polygones in regions:
        min_lon, min_lat, max_lon, max_lat = rectangle
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            continue
        if any(_dans_polygone(lon, lat, polygone) for polygone in polygones):
            return nom

    # Aucune région ne contient le point : on cherche le bord le plus proche,
    # dans la limite de RATTACHEMENT_MAX_DEG.
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
    """Ajoute le champ `region` à chaque fiche. Retourne le nombre de succès."""
    trouvees = 0
    for etablissement in etablissements:
        nom = region_de(etablissement["lat"], etablissement["lon"], regions)
        etablissement["region"] = nom
        trouvees += bool(nom)
    return trouvees


def regions_par_ville(etablissements: list[dict]) -> dict[str, str]:
    """Table ville -> région, déposée dans l'instantané.

    Le navigateur n'a pas les polygones : les lignes qu'il relit en direct
    déterminent leur région via cette table. En cas de ville rattachée à
    plusieurs régions, la plus fréquente l'emporte.
    """
    comptes: dict[str, Counter] = {}
    for etablissement in etablissements:
        if etablissement.get("region"):
            ville = etablissement["province"]
            comptes.setdefault(ville, Counter())[etablissement["region"]] += 1
    return {
        ville: compte.most_common(1)[0][0] for ville, compte in sorted(comptes.items())
    }


def completer_par_ville(
    etablissements: list[dict], villes_regions: dict[str, str]
) -> int:
    """Attribue une région, d'après la ville, aux fiches sans coordonnées."""
    complets = 0
    for etablissement in etablissements:
        if not etablissement.get("region"):
            etablissement["region"] = villes_regions.get(etablissement["province"], "")
            complets += bool(etablissement["region"])
    return complets


# --------------------------------------------------------------------------- #
# Écriture du fichier
# --------------------------------------------------------------------------- #


def render(
    etablissements: list[dict],
    genere_le: str,
    villes_regions: dict[str, str],
    champs: list[str],
) -> str:
    """Contenu de assets/instantane.js."""
    payload = {
        "genere_le": genere_le,
        "champs": champs,
        "regions_par_ville": villes_regions,
        "etablissements": etablissements,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        "/* FICHIER GÉNÉRÉ — NE PAS MODIFIER À LA MAIN.\n"
        " *\n"
        " * Produit par partenaires/build.py, régénéré chaque heure par\n"
        " * .github/workflows/instantane-partenaires.yml.\n"
        " *\n"
        " * Copie de secours du Google Sheet : les pages l'affichent au\n"
        " * chargement, puis la remplacent par le Sheet relu en direct. */\n"
        f"window.EARIARY_PARTENAIRES = {body};\n"
    )


def strip_timestamp(text: str) -> str:
    """Neutralise la date de génération, pour comparer deux instantanés."""
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
        # Une lecture ratée ne doit pas écraser un instantané valide.
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
