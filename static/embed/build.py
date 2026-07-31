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
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SHEET_ID = "1D15egjrBB_9eNCXC-THxZcSqvNtf7ttfssdcVDRu8Yo"
GID = "0"
CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"
)

BASE_DIR = Path(__file__).resolve().parent
OUTPUT = BASE_DIR / "assets" / "etablissements.js"

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


def render(etablissements: list[dict], genere_le: str) -> str:
    payload = {
        "genere_le": genere_le,
        "source": "Google Sheet (instantané)",
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

    genere_le = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    contenu = render(etablissements, genere_le)
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
        f"établissements, {localises} localisés."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
