"""
Géocode les adresses des pré-souscripteurs eAriary (une fois) et écrit :

  data/adresses_geocodees.csv        adresse -> latitude / longitude
  data/pre_souscripteurs_agreges.csv effectifs par adresse et type de compte

Le second fichier ne contient ni nom, ni téléphone, ni e-mail : c'est lui que
l'application utilise si le classeur Excel n'est pas présent (déploiement),
ce qui évite de publier des données personnelles.

Nominatim impose 1 requête/seconde : le script est lent par construction mais
ne tourne qu'à l'ajout de nouvelles adresses (les adresses déjà présentes dans
le cache ne sont pas re-interrogées).

Lancement :  python tools/geocode_souscripteurs.py
"""

import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "Stat_Inscription_eAr_10072026_final.xlsx"
CACHE = ROOT / "data" / "adresses_geocodees.csv"
AGGREGATE = ROOT / "data" / "pre_souscripteurs_agreges.csv"

ENDPOINT = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "carte-partenaires-eariary/1.0 (contact@esemahay.com)"}
PAUSE = 1.1  # secondes, politique d'usage de Nominatim


ATTEMPTS = 3  # tentatives par variante d'adresse avant de la déclarer perdue


def query(text):
    """Interroge Nominatim, avec reprise : une coupure réseau n'est pas un « rien trouvé ».

    Retourne la liste des résultats, ou None si toutes les tentatives ont échoué
    sur une erreur de transport — la distinction évite d'inscrire dans le cache
    un « introuvable » qui n'est en fait qu'un incident de connexion.
    """
    params = urllib.parse.urlencode(
        {"q": text, "format": "json", "limit": 1, "countrycodes": "mg"}
    )
    for attempt in range(1, ATTEMPTS + 1):
        try:
            req = urllib.request.Request(f"{ENDPOINT}?{params}", headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as exc:
            print(f"    ! {text} (essai {attempt}/{ATTEMPTS}) : {exc}", file=sys.stderr)
            time.sleep(PAUSE * 2 * attempt)
    return None


def geocode(address):
    """Essaie l'adresse complète puis, en cas d'échec, des variantes plus larges.

    « Anosibe, Antananarivo, Analamanga, Madagascar » devient successivement
    « Antananarivo, Analamanga, Madagascar » puis « Analamanga, Madagascar » :
    on perd en précision mais on garde le point sur la bonne zone.
    """
    parts = [p.strip() for p in str(address).split(",") if p.strip()]
    # Une adresse sans contexte administratif (« Paris », « G 149 », « A ») ne
    # peut pas être vérifiée : la recherche restreinte à Madagascar renvoie
    # toujours quelque chose — un boulevard, un commerce — mais rien ne dit que
    # c'est le bon endroit. Le résultat est conservé, marqué « incertaine ».
    structured = len(parts) > 1
    if structured and parts[-1].lower().startswith("madagas"):
        parts = parts[:-1]  # interroger « Madagascar » seul n'apprend rien

    network_error = False
    for start in range(len(parts)):
        candidate = ", ".join(parts[start:]) + ", Madagascar"
        hits = query(candidate)
        time.sleep(PAUSE)
        if hits is None:
            network_error = True
            continue
        if hits:
            if not structured:
                precision = "incertaine"
            else:
                precision = "exacte" if start == 0 else "approchée"
            return {
                "lat": float(hits[0]["lat"]),
                "lon": float(hits[0]["lon"]),
                "precision": precision,
                "correspondance": hits[0].get("display_name", ""),
            }

    precision = "erreur réseau" if network_error else "introuvable"
    return {"lat": "", "lon": "", "precision": precision, "correspondance": ""}


# Le champ « Adresse » recueille parfois une adresse e-mail (avec ou sans les
# points et l'arobase). Les fichiers de `data/` étant versionnés, ces saisies
# sont neutralisées avant écriture : elles n'ont aucune valeur géographique et
# identifient directement une personne.
EMAIL_LIKE = re.compile(
    r"@|(?:gmail|yahoo|hotmail|outlook|orange|moov|telma|esemahay)\.?(?:com|fr|mg)",
    re.IGNORECASE,
)
UNKNOWN_ADDRESS = "Adresse non renseignée"

# Le référentiel des types de compte. La colonne « Account » comporte elle aussi
# des saisies libres (une adresse e-mail y a été relevée) : tout ce qui en sort
# est ramené à « Non renseigné », comme le fait déjà l'application à l'affichage.
ACCOUNTS = {"Particulier", "Marchand", "Epicerie", "Épicerie", "Grande Entreprise"}
UNKNOWN_ACCOUNT = "Non renseigné"


def sanitize(address):
    text = str(address).strip()
    return UNKNOWN_ADDRESS if EMAIL_LIKE.search(text) else text


def sanitize_account(account):
    text = str(account).strip()
    return text if text in ACCOUNTS else UNKNOWN_ACCOUNT


def write_aggregate(df):
    """Écrit les effectifs par adresse et type de compte, sans donnée nominative."""
    counts = (
        df.assign(
            Adresse=df["Adresse"].apply(sanitize),
            Account=df["Account"].apply(sanitize_account),
        )
        .groupby(["Adresse", "Account"])
        .size()
        .reset_index(name="Inscrits")
        .sort_values(["Adresse", "Account"])
    )
    AGGREGATE.parent.mkdir(parents=True, exist_ok=True)
    counts.to_csv(AGGREGATE, index=False, encoding="utf-8")
    print(f"Agrégat écrit : {AGGREGATE} ({len(counts)} lignes)")


def main():
    source = pd.read_excel(XLSX, dtype=str)
    write_aggregate(source)
    addresses = source["Adresse"].apply(sanitize).unique()
    addresses = sorted(
        a
        for a in addresses
        if a and a.lower() not in ("nan", "none") and a != UNKNOWN_ADDRESS
    )

    known = {}
    if CACHE.exists():
        for row in csv.DictReader(CACHE.open(encoding="utf-8")):
            known[row["Adresse"]] = row

    # Les adresses résolues exactement ne sont jamais réinterrogées. `--retry`
    # reprend tout le reste (approché, introuvable, erreur réseau) : une variante
    # élargie peut n'avoir été retenue que parce que la connexion a lâché.
    retry = "--retry" in sys.argv
    todo = [
        a
        for a in addresses
        if a not in known or (retry and known[a]["precision"] != "exacte")
    ]
    print(f"{len(addresses)} adresses distinctes, {len(todo)} à géocoder")

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    for i, address in enumerate(todo, 1):
        result = geocode(address)
        known[address] = {"Adresse": address, **result}
        print(f"[{i}/{len(todo)}] {address} -> {result['precision']}")
        # Écriture à chaque itération : une interruption ne perd aucun résultat.
        with CACHE.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["Adresse", "lat", "lon", "precision", "correspondance"]
            )
            writer.writeheader()
            for key in sorted(known):
                writer.writerow(known[key])

    print(f"Cache écrit : {CACHE}")


if __name__ == "__main__":
    main()
