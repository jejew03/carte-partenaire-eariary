#!/usr/bin/env python3
"""Génère l'instantané de données de l'iframe (`assets/etablissements.js`).

L'iframe relit le Google Sheet en direct dans le navigateur, mais elle doit
afficher quelque chose immédiatement — et rester utilisable si le Sheet devient
privé, si le réseau tombe, ou si l'application hôte applique une politique de
sécurité (CSP) qui interdit l'appel à docs.google.com. D'où cet instantané,
versionné avec le reste du dossier et régénéré à la main :

    python embed/build.py            # relit le Sheet et réécrit l'instantané
    python embed/build.py --check    # compare sans écrire (code 1 si différent)

Les règles de lecture (détection de l'en-tête, recherche des colonnes par
mots-clés, format des coordonnées, corrections de libellés) reproduisent celles
de `load_data()` dans `app.py` ; `assets/data.js` en tient la version
JavaScript pour la relecture en direct. Toute évolution du Sheet se répercute
donc dans ces trois endroits.

Stdlib uniquement : ce script doit tourner sans le virtualenv du projet.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
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
OUTPUT = BASE_DIR / "assets" / "etablissements.js"
# Limites administratives déjà versionnées pour la choroplèthe de l'application.
ADM1 = BASE_DIR.parents[1] / "data" / "geo" / "mdg_adm1.geojson"

# Même expression que `app.py` : « -12.289942, 49.291381 », antislashs et
# virgules décimales tolérés. Une cellule qui ne correspond pas — « Introuvable,
# quartier Amparihy » — laisse l'établissement dans la liste, sans point.
COORD_RE = re.compile(
    r"^\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*[,;]\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*$"
)

# Fautes de frappe récurrentes du Sheet. Les catégories sont celles de
# `app.py` ; les provinces s'y ajoutent parce que l'iframe est destinée au
# public, où « Antsirananana » se remarque.
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


def fetch_csv(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "eariary-embed/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def find_header(rows: list[list[str]]) -> int:
    """Indice de la ligne d'en-tête : la première qui contient « province »."""
    for index, row in enumerate(rows[:10]):
        if "province" in " ".join(row).lower():
            return index
    return 0


def find_col(header: list[str], keywords: tuple[str, ...], default: int) -> int:
    for index, cell in enumerate(header):
        low = cell.lower()
        if any(keyword in low for keyword in keywords):
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
    """`str.capitalize()` de pandas : première lettre haute, le reste bas."""
    return value[:1].upper() + value[1:].lower() if value else value


def parse_rows(text: str) -> list[dict]:
    rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text))]
    rows = [row for row in rows if any(row)]
    if not rows:
        raise ValueError("feuille vide")

    header_index = find_header(rows)
    header = rows[header_index]
    body = rows[header_index + 1 :]

    # Le repli est la position habituelle dans le Sheet. Il ne sert que si le
    # mot-clé est absent de l'en-tête ; une colonne trouvée en position 0 doit
    # être retenue telle quelle, d'où le paramètre `default` plutôt qu'un `or`.
    i_prov = find_col(header, ("province", "région", "region"), 0)
    i_nom = find_col(header, ("établissement", "etablissement", "nom"), 1)
    i_cat = find_col(header, ("catégorie", "categorie", "type"), 2)
    i_geo = find_col(header, ("latitude", "longitude", "coord", "gps"), 3)

    def cell(row: list[str], index: int) -> str:
        return row[index] if index < len(row) else ""

    etablissements = []
    for row in body:
        nom = cell(row, i_nom)
        if not nom or nom.lower() in {"nan", "none"}:
            continue

        categorie = capitalize_fr(cell(row, i_cat))
        categorie = CATEGORY_FIXES.get(categorie, categorie) or EMPTY_LABEL
        province = cell(row, i_prov)
        province = PROVINCE_FIXES.get(province, province) or EMPTY_LABEL
        brut = cell(row, i_geo)
        lat, lon = parse_coords(brut)

        etablissements.append(
            {
                "nom": nom,
                "categorie": categorie,
                "province": province,
                "lat": lat,
                "lon": lon,
                "coordonnees_brutes": brut,
            }
        )
    return etablissements


# --------------------------------------------------------------------------- #
# Région administrative
# --------------------------------------------------------------------------- #
# Le Sheet ne porte pas la région : sa colonne « Province » mélange villes
# (Tolagnaro, Sambava) et anciennes provinces (Mahajanga, Toamasina). La région
# est donc déduite des coordonnées, par appartenance au polygone ADM1 —
# les mêmes limites que celles de la choroplèthe de l'application, déjà dans le
# dépôt. Aucun accès réseau, stdlib uniquement : pas de geopandas ici.

# Un point peut tomber hors de tout polygone — trait de côte simplifié à ~880 m,
# saisie GPS approximative. Il est alors rattaché à la région la plus proche,
# dans cette limite (en degrés, ~28 km) ; au-delà, la coordonnée est trop
# douteuse pour qu'on lui attribue une région.
RATTACHEMENT_MAX_DEG = 0.25


def _polygones(geometrie: dict) -> list[list[list[list[float]]]]:
    """Liste de polygones ; chacun est une liste d'anneaux (extérieur, trous)."""
    coordonnees = geometrie.get("coordinates") or []
    if geometrie.get("type") == "Polygon":
        return [coordonnees]
    if geometrie.get("type") == "MultiPolygon":
        return list(coordonnees)
    return []


def charger_regions(chemin: Path = ADM1) -> list[tuple[str, tuple, list]]:
    """`[(nom, rectangle englobant, polygones)]` — liste vide si le fichier manque.

    Son absence n'est pas une erreur : l'instantané se génère alors sans région,
    comme avant, et la page de tableau se rabat sur la ville.
    """
    if not chemin.exists():
        return []

    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    regions = []
    for entite in donnees.get("features", []):
        nom = (entite.get("properties") or {}).get("nom_zone")
        polygones = _polygones(entite.get("geometry") or {})
        if not nom or not polygones:
            continue
        sommets = [point for polygone in polygones for anneau in polygone for point in anneau]
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
    degré de longitude vaut environ 0,95 degré de latitude, et le rapport
    s'écarte encore aux latitudes hautes. Au segment et non au sommet le plus
    proche : une côte simplifiée peut n'avoir qu'un sommet tous les 900 m, et
    un point tombé juste au large serait sinon jugé lointain.
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
                    distance = _distance_segment(lon, lat, anneau[index], anneau[index + 1])
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
            comptes.setdefault(etablissement["province"], Counter())[etablissement["region"]] += 1
    return {
        ville: compte.most_common(1)[0][0]
        for ville, compte in sorted(comptes.items())
    }


def completer_par_ville(etablissements: list[dict], villes_regions: dict[str, str]) -> int:
    """Rattache par la ville les fiches qu'aucune coordonnée ne situe.

    Un établissement dont la cellule de coordonnées est inexploitable
    (« Introuvable, quartier Amparihy ») reste dans la liste ; il hérite de la
    région de sa ville plutôt que de tomber dans « Non renseignée ».
    """
    complets = 0
    for etablissement in etablissements:
        if not etablissement.get("region"):
            etablissement["region"] = villes_regions.get(etablissement["province"], "")
            complets += bool(etablissement["region"])
    return complets


def render(
    etablissements: list[dict],
    genere_le: str,
    villes_regions: dict[str, str] | None = None,
) -> str:
    payload = {
        "genere_le": genere_le,
        "source": "Google Sheet (instantané)",
        "regions_par_ville": villes_regions or {},
        "etablissements": etablissements,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        "/* Instantané des établissements partenaires eAriary.\n"
        "   Fichier généré — ne pas modifier à la main :\n"
        "       python embed/build.py\n"
        "   L'iframe l'affiche immédiatement, puis tente une relecture en\n"
        "   direct du Google Sheet et remplace ces données si elle aboutit. */\n"
        f"window.EARIARY_SNAPSHOT = {body};\n"
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

    etablissements = parse_rows(text)
    if not etablissements:
        print("Aucun établissement lisible dans le Sheet.", file=sys.stderr)
        return 1

    regions = charger_regions()
    if not regions:
        print(
            f"{ADM1.name} introuvable : instantané généré sans région.",
            file=sys.stderr,
        )
    situes = ajouter_regions(etablissements, regions)
    villes_regions = regions_par_ville(etablissements)
    situes += completer_par_ville(etablissements, villes_regions)

    genere_le = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    contenu = render(etablissements, genere_le, villes_regions)
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
        f"{OUTPUT.relative_to(BASE_DIR.parent)} : {len(etablissements)} "
        f"établissements, {localises} localisés, {situes} rattachés à une région "
        f"({len(villes_regions)} villes)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
