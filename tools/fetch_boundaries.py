"""
Récupère les limites administratives de Madagascar et écrit les fichiers
géographiques embarqués dans l'application :

  data/geo/mdg_adm1.geojson   Régions   (22)
  data/geo/mdg_adm2.geojson   Districts (119)
  data/geo/mdg_adm3.geojson   Communes  (1 579)
  data/geo/zones.csv          table de correspondance des trois niveaux

Source : HDX / OCHA « Madagascar - Subnational Administrative Boundaries »
(Common Operational Dataset, limites BNGRC nettoyées par OCHA, millésime
2018-10-31), licence CC BY 3.0 IGO. Voir data/geo/SOURCE.md pour le détail de
la licence, l'attribution à afficher et les sources écartées.

Ce script est le SEUL point du projet qui accède au réseau : l'application ne
télécharge jamais rien à l'exécution, elle lit uniquement les fichiers ci-dessus.
Il est idempotent — relancé, il réécrit les quatre fichiers à l'identique.

Lancement :  python tools/fetch_boundaries.py [--force] [--redownload]

  --force       reconstruit même si les fichiers de sortie existent déjà
  --redownload  ignore l'archive en cache et la retélécharge
  --cache-dir   répertoire du cache de téléchargement (hors dépôt par défaut)
"""

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import shapely
from shapely.geometry import mapping

ROOT = Path(__file__).resolve().parent.parent
GEO_DIR = ROOT / "data" / "geo"

# Archive shapefile du COD-AB Madagascar sur HDX (~66 Mo, tous les niveaux).
ARCHIVE_URL = (
    "https://data.humdata.org/dataset/26fa506b-0727-4d9d-a590-d2abee21ee22/"
    "resource/ed94d52e-349e-41be-80cb-62dc0435bd34/download/"
    "mdg_adm_bngrc_ocha_20181031_shp.zip"
)
ARCHIVE_NOM = "mdg_adm_bngrc_ocha_20181031_shp.zip"
SHP_MOTIF = "mdg_admbnda_adm{n}_BNGRC_OCHA_20181031"

HEADERS = {"User-Agent": "carte-partenaires-eariary/1.0 (contact@esemahay.com)"}
TENTATIVES = 3          # le réseau du poste est instable : on réessaie
DELAI_SOCKET = 60       # secondes sans octet reçu avant abandon d'une tentative
BACKOFF = 5             # secondes, multiplié par 3 à chaque échec (5, 15, 45)

# Un niveau administratif : nom du fichier produit, libellé du contrat, colonnes
# du shapefile portant le code/nom de la zone et ceux de son parent, et
# tolérance de simplification en degrés.
#
# Les tolérances sont calibrées pour un rendu Folium fluide à l'échelle du pays.
# 0,003° ≈ 330 m, 0,008° ≈ 880 m à cette latitude. La contrainte dimensionnante
# est mdg_adm3.geojson : 1 579 communes doivent tenir sous 1,5 Mo, ce qui borne
# le budget à ~35 sommets par commune (voir SOURCE.md).
NIVEAUX = (
    {
        "adm": 1,
        "fichier": "mdg_adm1.geojson",
        "niveau": "Région",
        "col_code": "ADM1_PCODE",
        "col_nom": "ADM1_EN",
        "col_code_parent": None,
        "col_nom_parent": None,
        "tolerance": 0.003,
    },
    {
        "adm": 2,
        "fichier": "mdg_adm2.geojson",
        "niveau": "District",
        "col_code": "ADM2_PCODE",
        "col_nom": "ADM2_EN",
        "col_code_parent": "ADM1_PCODE",
        "col_nom_parent": "ADM1_EN",
        "tolerance": 0.003,
    },
    {
        "adm": 3,
        "fichier": "mdg_adm3.geojson",
        "niveau": "Commune",
        "col_code": "ADM3_PCODE",
        "col_nom": "ADM3_EN",
        "col_code_parent": "ADM2_PCODE",
        "col_nom_parent": "ADM2_EN",
        "tolerance": 0.008,
    },
)

ZONES_CSV = "zones.csv"
DECIMALES = 5           # ~1 m : au-delà, on paierait des octets pour du bruit
PRECISION = 10 ** -DECIMALES

# Membre `crs` héritée de GeoJSON 2008 : RFC 7946 impose déjà WGS 84, mais
# l'écrire rend le CRS vérifiable à la lecture du fichier (et geopandas le
# relit bien comme EPSG:4326).
CRS_MEMBRE = {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}

# Préfixes techniques que la source accole parfois au nom : « Cu Morombe » est
# la commune urbaine de Morombe. On les retire pour garder un nom affichable,
# sans toucher au nom lui-même.
PREFIXES = re.compile(
    r"^(?:c\.?u\.?|commune\s+urbaine|commune\s+rurale|commune|district|region|région)"
    r"\s*(?:de\s+|du\s+|d')?",
    re.IGNORECASE,
)

# La source translittère en ASCII et remplace l'apostrophe par une espace, ce
# qui casse un nom de région. Table de corrections explicite, volontairement
# minimale : on ne réécrit que ce qui est manifestement abîmé.
CORRECTIONS = {
    "Amoron I Mania": "Amoron'i Mania",
}


# --------------------------------------------------------------------------- #
# Téléchargement
# --------------------------------------------------------------------------- #

def telecharger(url, destination):
    """Télécharge `url` vers `destination`, avec reprise et backoff.

    Écrit d'abord un fichier `.part` renommé à la fin : une coupure ne laisse
    jamais une archive tronquée que la prochaine exécution prendrait pour valide.
    """
    partiel = destination.with_suffix(destination.suffix + ".part")
    for essai in range(1, TENTATIVES + 1):
        try:
            requete = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(requete, timeout=DELAI_SOCKET) as reponse:
                attendu = int(reponse.headers.get("Content-Length") or 0)
                with partiel.open("wb") as sortie:
                    shutil.copyfileobj(reponse, sortie, length=1 << 20)
            recu = partiel.stat().st_size
            if attendu and recu != attendu:
                raise OSError(f"téléchargement incomplet ({recu}/{attendu} octets)")
            partiel.replace(destination)
            print(f"  téléchargé : {recu / 1e6:.1f} Mo")
            return
        except Exception as exc:
            partiel.unlink(missing_ok=True)
            print(f"  ! essai {essai}/{TENTATIVES} : {exc}", file=sys.stderr)
            if essai < TENTATIVES:
                attente = BACKOFF * 3 ** (essai - 1)
                print(f"    nouvelle tentative dans {attente} s", file=sys.stderr)
                time.sleep(attente)
    raise SystemExit(
        "Échec du téléchargement après "
        f"{TENTATIVES} tentatives : {url}\n"
        "Aucun fichier n'a été écrit — les données existantes sont intactes."
    )


def obtenir_archive(cache_dir, redownload):
    """Retourne le chemin de l'archive shapefile, en la téléchargeant au besoin."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / ARCHIVE_NOM
    if archive.exists() and not redownload:
        try:
            with zipfile.ZipFile(archive) as zf:
                if zf.namelist():
                    print(f"archive en cache : {archive} ({archive.stat().st_size / 1e6:.1f} Mo)")
                    return archive
        except zipfile.BadZipFile:
            print("  archive en cache illisible, retéléchargement", file=sys.stderr)
            archive.unlink(missing_ok=True)
    print(f"téléchargement de {ARCHIVE_URL}")
    telecharger(ARCHIVE_URL, archive)
    return archive


def extraire(archive, destination):
    """Extrait les shapefiles ADM1/2/3 (l'ADM4 — 17 465 fokontany — est inutile ici)."""
    destination.mkdir(parents=True, exist_ok=True)
    prefixes = tuple(SHP_MOTIF.format(n=n) for n in (1, 2, 3))
    with zipfile.ZipFile(archive) as zf:
        membres = [m for m in zf.namelist() if m.startswith(prefixes)]
        if not membres:
            raise SystemExit(f"archive inattendue : aucun shapefile ADM1/2/3 dans {archive}")
        zf.extractall(destination, members=membres)
    return destination


# --------------------------------------------------------------------------- #
# Normalisation des noms
# --------------------------------------------------------------------------- #

def nettoyer_nom(brut):
    """Normalise un nom de zone pour l'affichage.

    Espaces multiples réduits, préfixe technique retiré, initiale de chaque mot
    en capitale. Les accents, tirets et apostrophes présents sont conservés
    (`unicodedata.normalize` en NFC pour éviter deux encodages du même accent),
    les mots déjà capitalisés sont laissés tels quels — c'est ce qui préserve
    « Antsirabe I », « Toliary-II » ou « 1er Arrondissement ».
    """
    nom = unicodedata.normalize("NFC", str(brut or "")).strip()
    nom = re.sub(r"\s+", " ", nom)
    nom = PREFIXES.sub("", nom).strip()
    nom = "".join(_capitaliser(jeton) for jeton in re.split(r"([ \-/])", nom))
    return CORRECTIONS.get(nom, nom)


def _capitaliser(jeton):
    """Met l'initiale en capitale, sauf si le mot en contient déjà une ou commence
    par un chiffre (« 1er » ne doit pas devenir « 1Er »)."""
    if not jeton or any(c.isupper() for c in jeton) or not jeton[0].isalpha():
        return jeton
    return jeton[0].upper() + jeton[1:]


# --------------------------------------------------------------------------- #
# Géométries
# --------------------------------------------------------------------------- #

def simplifier(geometries, tolerance):
    """Simplifie un pavage de polygones sans créer ni trou ni recouvrement.

    `coverage_simplify` simplifie les arêtes *partagées* de façon identique de
    part et d'autre : contrairement à un `simplify()` polygone par polygone, les
    communes voisines restent jointives. `set_precision` arrondit ensuite les
    sommets à la grille des 5 décimales effectivement écrites dans le fichier —
    l'arrondi est donc appliqué avant les contrôles de validité, et non après.
    """
    geometries = shapely.coverage_simplify(
        geometries, tolerance=tolerance, simplify_boundary=True
    )
    geometries = shapely.set_precision(geometries, PRECISION)
    # Filet de sécurité : l'arrondi peut, sur une pointe très fine, produire un
    # anneau dégénéré. `make_valid` (successeur de buffer(0)) le répare.
    invalides = ~shapely.is_valid(geometries)
    if invalides.any():
        print(f"  {int(invalides.sum())} géométrie(s) réparée(s) par make_valid()")
        geometries = shapely.make_valid(geometries)
    return geometries


def arrondir(valeur):
    """Arrondit récursivement les coordonnées d'un objet GeoJSON."""
    if isinstance(valeur, float):
        return round(valeur, DECIMALES)
    if isinstance(valeur, (list, tuple)):
        return [arrondir(element) for element in valeur]
    return valeur


def construire_features(gdf, niveau, geometries):
    """Assemble les Features au format du contrat d'interface.

    Cinq propriétés, exactement : code_zone, nom_zone, niveau, code_parent,
    nom_parent (les deux dernières à null au niveau Région).
    """
    codes = gdf[niveau["col_code"]].tolist()
    noms = gdf[niveau["col_nom"]].tolist()
    codes_parents = (
        gdf[niveau["col_code_parent"]].tolist() if niveau["col_code_parent"]
        else [None] * len(gdf)
    )
    noms_parents = (
        gdf[niveau["col_nom_parent"]].tolist() if niveau["col_nom_parent"]
        else [None] * len(gdf)
    )

    features = []
    for position in range(len(gdf)):
        code = str(codes[position]).strip()
        if not code or code.lower() == "nan":
            raise SystemExit(f"{niveau['fichier']} : code de zone vide à la ligne {position}")
        features.append({
            "type": "Feature",
            "properties": {
                "code_zone": code,
                "nom_zone": nettoyer_nom(noms[position]),
                "niveau": niveau["niveau"],
                "code_parent": (
                    str(codes_parents[position]).strip()
                    if codes_parents[position] is not None else None
                ),
                "nom_parent": (
                    nettoyer_nom(noms_parents[position])
                    if noms_parents[position] is not None else None
                ),
            },
            "geometry": arrondir(mapping(geometries[position])),
        })
    return features


def ecrire_geojson(chemin, features):
    """Écrit un GeoJSON compact (ni espace ni retour à la ligne superflu)."""
    collection = {"type": "FeatureCollection", "crs": CRS_MEMBRE, "features": features}
    texte = json.dumps(collection, separators=(",", ":"), ensure_ascii=False)
    chemin.write_text(texte + "\n", encoding="utf-8")
    return len(texte.encode("utf-8"))


def ecrire_zones_csv(chemin, features_par_niveau):
    """Écrit la table de correspondance des trois niveaux réunis."""
    with chemin.open("w", encoding="utf-8", newline="") as sortie:
        redacteur = csv.writer(sortie)
        redacteur.writerow(["code_zone", "nom_affiche", "niveau", "code_parent", "nom_parent"])
        for features in features_par_niveau:
            for feature in features:
                p = feature["properties"]
                redacteur.writerow([
                    p["code_zone"], p["nom_zone"], p["niveau"],
                    p["code_parent"] or "", p["nom_parent"] or "",
                ])


# --------------------------------------------------------------------------- #
# Vérifications
# --------------------------------------------------------------------------- #

def _zones_non_jointives(geometries):
    """Nombre de zones dont une arête mitoyenne ne coïncide pas avec sa voisine."""
    if shapely.coverage_is_valid(geometries):
        return 0
    aretes = shapely.coverage_invalid_edges(geometries)
    return sum(
        1 for arete in aretes if arete is not None and not shapely.is_empty(arete)
    )


def verifier(niveau, gdf, geometries, features, taille, codes_parents_connus):
    """Contrôle et journalise l'état d'un niveau. Retourne le nombre d'anomalies."""
    anomalies = 0
    fichier = niveau["fichier"]
    codes = [f["properties"]["code_zone"] for f in features]

    print(f"\n{fichier}")
    print(f"  zones            : {len(features)}")
    print(f"  taille           : {taille / 1e6:.3f} Mo")
    print(f"  sommets          : {int(shapely.get_num_coordinates(geometries).sum())}"
          f"  (source : {int(shapely.get_num_coordinates(gdf.geometry.values).sum())})")
    print(f"  crs source       : {gdf.crs}")

    doublons = len(codes) - len(set(codes))
    if doublons:
        anomalies += doublons
        print(f"  ! {doublons} code_zone en doublon")

    invalides = int((~shapely.is_valid(geometries)).sum())
    vides = int(shapely.is_empty(geometries).sum())
    print(f"  invalides        : {invalides}")
    print(f"  vides            : {vides}")
    anomalies += invalides + vides

    # Pavage : ni trou ni recouvrement entre zones voisines. On compte les zones
    # fautives AVANT et APRÈS simplification, parce que la source en contient
    # déjà quelques-unes (arêtes mitoyennes non nodées, cf. SOURCE.md) : seul un
    # défaut *ajouté* par la simplification est une anomalie de notre fait.
    fautives_source = _zones_non_jointives(gdf.geometry.values)
    fautives = _zones_non_jointives(geometries)
    print(f"  pavage : {fautives} zone(s) non jointive(s)"
          f"  (source : {fautives_source})")
    if fautives > fautives_source:
        anomalies += fautives - fautives_source
        print(f"  ! la simplification a créé {fautives - fautives_source} défaut(s) de pavage")

    # Perte d'aire due à la simplification, en valeur absolue cumulée.
    aire_source = shapely.area(gdf.geometry.values).sum()
    aire_finale = shapely.area(geometries).sum()
    print(f"  écart d'aire     : {abs(aire_finale - aire_source) / aire_source * 100:.3f} %")

    if codes_parents_connus is not None:
        parents = {f["properties"]["code_parent"] for f in features}
        orphelins = sorted(p for p in parents if p not in codes_parents_connus)
        print(f"  parents inconnus : {len(orphelins)}")
        if orphelins:
            anomalies += len(orphelins)
            print(f"  ! codes orphelins : {orphelins[:10]}")
    return anomalies


def relire(chemin):
    """Relit le fichier produit avec geopandas : CRS effectif et temps de lecture."""
    depart = time.perf_counter()
    gdf = gpd.read_file(chemin)
    duree = time.perf_counter() - depart
    proprietes = set(gdf.columns) - {"geometry"}
    attendu = {"code_zone", "nom_zone", "niveau", "code_parent", "nom_parent"}
    manquantes = attendu - proprietes
    print(f"  relecture        : {len(gdf)} zones en {duree:.2f} s, crs={gdf.crs}")
    if manquantes:
        print(f"  ! propriétés manquantes : {sorted(manquantes)}")
    return len(manquantes)


# --------------------------------------------------------------------------- #
# Programme principal
# --------------------------------------------------------------------------- #

def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    analyseur.add_argument("--force", action="store_true",
                           help="reconstruit même si les fichiers existent déjà")
    analyseur.add_argument("--redownload", action="store_true",
                           help="ignore l'archive en cache et la retélécharge")
    analyseur.add_argument("--cache-dir", type=Path,
                           default=Path(tempfile.gettempdir()) / "mdg_cod_ab",
                           help="cache de téléchargement (hors dépôt : l'archive pèse 66 Mo)")
    options = analyseur.parse_args()

    GEO_DIR.mkdir(parents=True, exist_ok=True)
    sorties = [GEO_DIR / n["fichier"] for n in NIVEAUX] + [GEO_DIR / ZONES_CSV]
    if all(chemin.exists() for chemin in sorties) and not options.force:
        print("Fichiers déjà présents dans data/geo — rien à faire (--force pour reconstruire).")
        for chemin in sorties:
            print(f"  {chemin.name:<20} {chemin.stat().st_size / 1e6:.3f} Mo")
        return 0

    archive = obtenir_archive(options.cache_dir, options.redownload)
    with tempfile.TemporaryDirectory(prefix="mdg_shp_") as travail:
        shp_dir = extraire(archive, Path(travail))

        anomalies = 0
        codes_par_niveau = {}
        features_par_niveau = []

        for niveau in NIVEAUX:
            chemin_shp = shp_dir / (SHP_MOTIF.format(n=niveau["adm"]) + ".shp")
            gdf = gpd.read_file(chemin_shp)

            # CRS impératif : la source est déjà en WGS 84, on le rend explicite
            # plutôt que de le supposer.
            if gdf.crs is None:
                raise SystemExit(f"{chemin_shp.name} : CRS absent, impossible de reprojeter")
            if gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(4326)

            geometries = simplifier(gdf.geometry.values, niveau["tolerance"])
            features = construire_features(gdf, niveau, geometries)
            taille = ecrire_geojson(GEO_DIR / niveau["fichier"], features)

            parents_connus = (
                codes_par_niveau.get(niveau["adm"] - 1) if niveau["adm"] > 1 else None
            )
            anomalies += verifier(niveau, gdf, geometries, features, taille, parents_connus)
            anomalies += relire(GEO_DIR / niveau["fichier"])

            codes_par_niveau[niveau["adm"]] = {f["properties"]["code_zone"] for f in features}
            features_par_niveau.append(features)

    ecrire_zones_csv(GEO_DIR / ZONES_CSV, features_par_niveau)
    total = sum(len(f) for f in features_par_niveau)
    print(f"\n{ZONES_CSV}")
    print(f"  lignes           : {total}")
    print(f"  taille           : {(GEO_DIR / ZONES_CSV).stat().st_size / 1e6:.3f} Mo")

    # Garde-fou : la cible de 1,5 Mo sur les communes conditionne la fluidité du
    # rendu Folium. Si elle est dépassée, il faut relever la tolérance ADM3.
    poids_adm3 = (GEO_DIR / "mdg_adm3.geojson").stat().st_size
    if poids_adm3 > 1_500_000:
        anomalies += 1
        print(f"\n! mdg_adm3.geojson dépasse la cible de 1,5 Mo ({poids_adm3 / 1e6:.3f} Mo) :"
              " relever la tolérance ADM3 dans NIVEAUX.", file=sys.stderr)

    print(f"\n{'OK' if anomalies == 0 else f'{anomalies} ANOMALIE(S)'} — data/geo à jour.")
    return 0 if anomalies == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
