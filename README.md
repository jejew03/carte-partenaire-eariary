# Carte des établissements — Madagascar

Application Streamlit affichant sur une carte les établissements listés dans le Google Sheet.

## Installation

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Données

L'app lit le Google Sheet en direct via l'URL d'export CSV :
`https://docs.google.com/spreadsheets/d/<ID>/export?format=csv&gid=0`

**Important :** pour que la lecture en direct fonctionne, le Sheet doit être partagé
en « Tous les utilisateurs disposant du lien → Lecteur ».
Sinon l'app bascule automatiquement sur la copie embarquée dans `app.py`
(constante `FALLBACK_CSV`) et l'indique dans la barre latérale.

Le cache est de 5 minutes ; le bouton « Recharger les données » force la relecture.

### Pré-souscripteurs eAriary

La liste des inscriptions (colonnes `Adresse` et `Account`) alimente une
seconde couche de la carte. Elle ne contient aucune coordonnée : les adresses
sont uniformisées puis géocodées, une fois, et le résultat est mis en cache.

**Depuis l'application** — section « Importer la liste des pré-inscrits », en
bas de page : déposez l'export (CSV ou Excel), l'app uniformise les adresses,
propose les rapprochements douteux, géocode les nouvelles et réécrit les
fichiers de `data/`. C'est la voie normale, et le seul endroit de
l'application qui écrive sur le disque ou accède au réseau.

**En ligne de commande**, à partir du classeur
`Stat_Inscription_eAr_<date>_final.xlsx` — même résultat, sans interface :

```bash
python tools/geocode_souscripteurs.py           # nouvelles adresses seulement
python tools/geocode_souscripteurs.py --retry   # reprend tout ce qui n'est pas « exacte »
```

Les deux voies écrivent dans `data/` :

| Fichier | Contenu | Versionné |
|---|---|---|
| `adresses_geocodees.csv` | adresse → latitude/longitude + précision | oui |
| `pre_souscripteurs_agreges.csv` | effectifs par adresse et type de compte | oui |
| `adresses_normalisees.csv` | libellé importé → libellé retenu (fusions confirmées) | oui |

Le fichier importé, lui, **n'est jamais écrit sur le disque**, et le classeur
Excel **n'est pas versionné** (`.gitignore`) : tous deux contiennent des noms,
téléphones et e-mails, dont rien ne sort de la mémoire de la session. En
l'absence du classeur — sur un déploiement, par exemple — l'app repart de
l'agrégat anonyme et affiche exactement la même carte.

Quand les deux existent, **c'est le plus récent qui gagne** : un import fait
depuis l'interface réécrit l'agrégat sans toucher au classeur, et doit
l'emporter sur lui.

#### Uniformisation des adresses

Le géocodeur ne rapproche pas « TAMATAVE » de « Toamasina » : deux graphies
d'un même lieu donnent deux points sur la carte. `pre_inscrits.py` applique
donc, à chaque import, des règles **volontairement conservatrices** — elles ne
rapprochent que ce qui est certain :

- espaces et virgules resserrés, ponctuation de fin retirée ;
- casse rétablie sur les saisies tout en capitales ou tout en bas
  (« ANTANANARIVO » → « Antananarivo ») ; une casse composée est un choix de
  saisie, on n'y touche pas ;
- noms usuels et coloniaux ramenés au nom officiel (« Tamatave » → « Toamasina »,
  « Fort Dauphin » → « Tolagnaro », « Tana » → « Antananarivo ») ;
- « Madagascar » ajouté aux adresses qui portent déjà une ville ou une région,
  et à elles seules — une localité isolée qui en hériterait passerait pour une
  adresse structurée, que le géocodeur tiendrait alors pour sûre ;
- adresses e-mail neutralisées en « Adresse non renseignée ».

Ces règles ne réécrivent **aucune** des adresses déjà géocodées (un test le
vérifie sur le corpus complet) : le cache reste valide d'un import à l'autre.

Ce qu'elles ne peuvent pas trancher — « Ambatatolampy » et « Ambatolampy »,
« Mahitsy, Analamanga » et « Mahitsy, Antananarivo, Analamanga » — est
**proposé, jamais appliqué d'office** : « Itaosy » et « Itasy » se ressemblent
autant et désignent deux endroits différents. Chaque fusion confirmée est
inscrite dans `adresses_normalisees.csv` et vaut pour tous les imports
suivants.

Le géocodeur (Nominatim, 1 requête/seconde) essaie l'adresse complète puis des
variantes de plus en plus larges : `Anosibe, Antananarivo, Analamanga` devient
au besoin `Antananarivo, Analamanga` puis `Analamanga`. La colonne `precision`
distingue « exacte » d'« approchée ».

### Limites administratives (choroplèthe)

Les inscrits sont rendus par zone administrative colorée. Les géométries sont
**embarquées dans le dépôt** — l'application ne fait aucun appel réseau au
runtime — et régénérées uniquement par

```bash
python tools/fetch_boundaries.py            # ne retélécharge pas si data/geo/ est déjà rempli
python tools/fetch_boundaries.py --force    # régénère tout
```

| Fichier | Niveau | Zones | Taille |
|---|---|---|---|
| `data/geo/mdg_adm1.geojson` | Région | 22 | 0,49 Mo |
| `data/geo/mdg_adm2.geojson` | District | 119 | 0,91 Mo |
| `data/geo/mdg_adm3.geojson` | Commune | 1 579 | 1,44 Mo |
| `data/geo/zones.csv` | les trois réunis | 1 720 | 0,09 Mo |

Chaque entité porte `code_zone`, `nom_zone`, `niveau`, `code_parent`,
`nom_parent`, en EPSG:4326. **`code_zone` (pcode) est le seul identifiant
fiable** : 150 noms de communes sont des homonymes (`Morafeno` apparaît 7 fois),
d'où l'affichage systématique du parent dans l'interface.

**Source : BNGRC / OCHA, « Madagascar – Subnational Administrative Boundaries »
(COD-AB, millésime 2018-10-31), via HDX — licence CC BY 3.0 IGO**, qui autorise
la redistribution et l'usage commercial sous réserve d'attribution. Détail
complet de la provenance dans [`data/geo/SOURCE.md`](data/geo/SOURCE.md).

geoBoundaries a été écarté malgré une licence compatible : ses entités ne
portent aucun code de parent, et son ADM1 (OSM 2017, ODbL) ne s'emboîte pas
dans ses ADM2/ADM3 (qui sont ce même COD-AB) — deux millésimes et deux licences
mélangés. Passer par HDX remonte à l'amont avec les pcodes intacts.

Deux limites connues, assumées : le COD-AB 2018 précède le découpage de 2021 et
compte donc **22 régions et non 23** (Vatovavy Fitovinany n'est pas scindée) ;
et la simplification à ~880 m suffit à un choroplèthe national mais reste
grossière sur les petites communes de l'agglomération d'Antananarivo.

## Fonctionnalités

- Carte Folium avec clustering, marqueurs colorés par catégorie, fonds
  interchangeables (plan clair par défaut, plan détaillé, satellite)
- Popup par établissement + lien direct vers Google Maps
- Choroplèthe des pré-souscripteurs par zone administrative, au choix Région /
  District / Commune : remplissage en **quantiles** (des intervalles égaux
  laisseraient Antananarivo, 796 inscrits sur 1 072, écraser toute l'échelle),
  zones sans inscrit en gris distinct, infobulle au survol et popup détaillé au
  clic — aucune donnée nominative n'atteint la carte
- Trois métriques de coloriage : valeur absolue, densité (inscrits par
  établissement), part du total en %
- Panneau de détail sous la carte : cliquez une zone pour obtenir ses localités
  triables et l'export CSV de cette seule zone
- Bandeau d'indicateurs : inscrits localisés, zones couvertes, zone n°1, taux de
  couverture du niveau choisi
- Filtres : province/ville, catégorie, recherche par nom ; région et type de
  compte pour les pré-souscripteurs
- Tableau détaillé + export CSV de la sélection, récapitulatif par localité
  des pré-souscripteurs + export
- Sections dédiées aux lignes dont les coordonnées ne sont pas exploitables
- **Import de la liste des pré-inscrits** depuis l'interface : dépôt d'un CSV
  ou d'un Excel, uniformisation des adresses, rapprochements proposés à
  confirmer, géocodage des nouvelles adresses avec barre de progression, puis
  mise à jour de la carte — rien n'est écrit ni envoyé avant le clic final

Si `data/geo/` est absent, l'application n'échoue pas : elle le signale et
retombe sur l'ancien rendu en cercles proportionnels.

## Architecture

| Fichier | Rôle |
|---|---|
| `app.py` | interface Streamlit, rendu Folium, filtres, import |
| `pre_inscrits.py` | lecture du fichier importé, uniformisation des adresses, fusions, agrégat, géocodage |
| `geo_aggregate.py` | jointure spatiale points → polygones et agrégation par zone |
| `tools/geocode_souscripteurs.py` | même chaîne, hors ligne, à partir du classeur Excel |
| `tools/fetch_boundaries.py` | récupération et simplification des limites (réseau) |
| `tests/test_geo_aggregate.py` | tests du moteur d'agrégation |
| `tests/test_pre_inscrits.py` | tests des règles d'import (sans réseau) |
| `tests/test_import_ui.py` | test de bout en bout de la section d'import, via `AppTest` |

Les règles de l'import ne vivent qu'une fois, dans `pre_inscrits.py` :
l'interface et le script hors ligne y puisent tous les deux. Le géocodage est
le seul accès réseau au runtime, et il est contenu dans le bouton d'import ;
`tools/fetch_boundaries.py` ne tourne qu'à la main. L'agrégation rattache chaque point au
polygone qui le contient (`sjoin` / `within`) ; un point qui ne tombe dans aucun
polygone — imprécision GPS, trait de côte — est rattaché au polygone le plus
proche, distance calculée en projection métrique (UTM 38S) et non en degrés, et
signalé comme rattachement approximatif.

```bash
python -m pytest tests/ -q
```

## Pages publiques

Les pages publiques à intégrer vivent dans un **dépôt séparé**,
[`partenaires-eariary`](https://github.com/jejew03/partenaires-eariary) : elles n'ont ni le cycle de vie, ni le
public, ni les dépendances de cette application. Deux pages autonomes, qui ne
montrent ni les pré-souscripteurs ni les indicateurs internes.

| Page | Contenu |
|---|---|
| `carte.html` | carte et liste, filtres ville et catégorie |
| `tableau.html` | registre trié, filtres **région** et **type de marchand**, lien Google Maps par ligne — ni Leaflet ni tuiles |

Elles sont publiées par GitHub Pages depuis `main` — **ce sont les adresses à
diffuser**, elles ne demandent aucune connexion :

```
https://jejew03.github.io/partenaires-eariary/carte.html
https://jejew03.github.io/partenaires-eariary/tableau.html
```

L'application affiche ces liens, le code à copier et un aperçu dans sa vue
« Intégration ». Elle n'héberge aucune copie des pages : il n'existe qu'une
seule version en ligne. Voir le [README du dépôt](https://github.com/jejew03/partenaires-eariary#readme) pour les
paramètres d'URL, les messages `postMessage`, les colonnes du Sheet et les
conventions de code.

Les pages relisent le Google Sheet toutes les cinq minutes : une ligne ajoutée
à la feuille y apparaît sans rechargement. Une copie de secours embarquée est
régénérée chaque heure par un workflow de l'autre dépôt.

La colonne « Région » du tableau ne vient pas du Sheet, dont la colonne
« Province » mélange villes et anciennes provinces : elle est déduite des
coordonnées par appartenance au polygone ADM1 de `data/geo/mdg_adm1.geojson`.
**Ce fichier est dupliqué** dans le dépôt des pages, qui en a besoin sans
dépendre de celui-ci ; les deux sont figés (millésime COD-AB 2018).

## Design

L'application se lit en **quatre vues**, choisies par le sélecteur sous la
titraille : *Carte* (indicateurs, choroplèthe, carte), *Établissements*
(tableau et export), *Pré-inscrits* (récapitulatif et import), *Intégration*
(code des iframes). Les filtres restent dans la barre latérale, communs aux
quatre — c'est le même jeu de données sous quatre angles, pas quatre pages.

Un sélecteur plutôt que `st.tabs` : celui-ci construit les quatre panneaux à
chaque exécution, y compris ceux qu'on ne regarde pas. Un tableau mesuré
pendant que son onglet est masqué s'installe à 49 px de large et n'en bouge
plus, même après redimensionnement, et la carte se reconstruit à chaque clic
pour rien. Ici, seule la vue demandée est construite ; en changer relance le
script, sur des données déjà en cache.

Le thème (couleurs, polices, rayons, bordures, style des tableaux) est défini
dans `.streamlit/config.toml` ; `app.py` n'ajoute que les quelques règles CSS
que le thème n'expose pas (en-tête, légende, cartes d'indicateurs).

Conventions :

- **aucun emoji** dans l'interface — les icônes viennent de Material Symbols
  (`:material/...` côté Streamlit) et de Font Awesome 6 (marqueurs de la carte) ;
- la couleur n'est jamais la seule information : chaque catégorie de la légende
  porte son libellé, et chaque marqueur une icône distincte ;
- une sélection de filtre vide équivaut à « tout afficher ».

## Structure attendue du Sheet

| Province | Nom de l'établissement | Catégorie | Latitude / longitude |
|---|---|---|---|

La ligne d'en-tête est détectée automatiquement (celle contenant « Province »),
et les colonnes sont retrouvées par mots-clés — l'ordre exact n'est donc pas critique.
