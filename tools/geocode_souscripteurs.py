"""
Géocode les adresses des pré-souscripteurs eAriary (une fois) et écrit :

  data/adresses_geocodees.csv        adresse -> latitude / longitude
  data/pre_souscripteurs_agreges.csv effectifs par adresse et type de compte

Le second fichier ne contient ni nom, ni téléphone, ni e-mail : c'est lui que
l'application utilise si le classeur Excel n'est pas présent (déploiement),
ce qui évite de publier des données personnelles.

Les règles — uniformisation des adresses, référentiel des types de compte,
géocodage — vivent dans `pre_inscrits.py`, que l'import depuis l'interface
utilise aussi. Ce script est la voie hors ligne vers le même résultat : il part
du classeur, prend son temps, et peut reprendre les résolutions douteuses.

Nominatim impose 1 requête/seconde : le script est lent par construction mais
ne tourne qu'à l'ajout de nouvelles adresses (les adresses déjà présentes dans
le cache ne sont pas re-interrogées).

Lancement :  python tools/geocode_souscripteurs.py
             python tools/geocode_souscripteurs.py --retry
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pre_inscrits  # noqa: E402

XLSX = ROOT / "Stat_Inscription_eAr_10072026_final.xlsx"


def main():
    source = pd.read_excel(XLSX, dtype=str)
    col_adresse, col_compte = pre_inscrits.colonnes_utiles(source)
    prepare = pre_inscrits.preparer(source, col_adresse, col_compte)

    agregat = pre_inscrits.agreger(prepare)
    pre_inscrits.enregistrer_agregat(agregat)
    print(f"Agrégat écrit : {pre_inscrits.AGREGAT} ({len(agregat)} lignes)")

    adresses = sorted(set(prepare["Adresse"]) - {pre_inscrits.ADRESSE_INCONNUE})
    cache = pre_inscrits.charger_cache_geo()

    # Les adresses résolues exactement ne sont jamais réinterrogées. `--retry`
    # reprend tout le reste (approché, introuvable, erreur réseau) : une variante
    # élargie peut n'avoir été retenue que parce que la connexion a lâché.
    retry = "--retry" in sys.argv
    todo = [
        a
        for a in adresses
        if a not in cache or (retry and cache[a].get("precision") != "exacte")
    ]
    print(f"{len(adresses)} adresses distinctes, {len(todo)} à géocoder")

    for i, adresse in enumerate(todo, 1):
        resultat = pre_inscrits.geocoder(adresse)
        cache[adresse] = {"Adresse": adresse, **resultat}
        print(f"[{i}/{len(todo)}] {adresse} -> {resultat['precision']}")
        # Écriture à chaque itération : une interruption ne perd aucun résultat.
        pre_inscrits.enregistrer_cache_geo(cache)

    print(f"Cache écrit : {pre_inscrits.CACHE_GEO}")


if __name__ == "__main__":
    main()
