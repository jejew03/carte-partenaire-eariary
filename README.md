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

Le classeur `Stat_Inscription_eAr_<date>_final.xlsx` (colonnes `Adresse` et
`Account`) alimente une seconde couche de la carte. Il ne contient aucune
coordonnée : les adresses sont géocodées une fois par

```bash
python tools/geocode_souscripteurs.py           # nouvelles adresses seulement
python tools/geocode_souscripteurs.py --retry   # reprend tout ce qui n'est pas « exacte »
```

qui écrit dans `data/` :

| Fichier | Contenu | Versionné |
|---|---|---|
| `adresses_geocodees.csv` | adresse → latitude/longitude + précision | oui |
| `pre_souscripteurs_agreges.csv` | effectifs par adresse et type de compte | oui |

Le classeur Excel, lui, **n'est pas versionné** (`.gitignore`) : il contient des
noms, téléphones et e-mails. En son absence — sur un déploiement, par exemple —
l'app repart de l'agrégat anonyme et affiche exactement la même carte.

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

Si `data/geo/` est absent, l'application n'échoue pas : elle le signale et
retombe sur l'ancien rendu en cercles proportionnels.

## Architecture

| Fichier | Rôle |
|---|---|
| `app.py` | interface Streamlit, rendu Folium, filtres |
| `geo_aggregate.py` | jointure spatiale points → polygones et agrégation par zone |
| `tools/geocode_souscripteurs.py` | géocodage des adresses d'inscription (réseau) |
| `tools/fetch_boundaries.py` | récupération et simplification des limites (réseau) |
| `static/embed/` | pages publiques à intégrer par iframe — carte et tableau ([documentation](static/embed/README.md)) |
| `tests/test_geo_aggregate.py` | tests du moteur d'agrégation |
| `tests/test_embed_build.py` | tests de la lecture du Sheet et du rattachement à la région |

Les deux scripts de `tools/` sont les seuls points du projet qui accèdent au
réseau, et ils ne tournent qu'à la main. L'agrégation rattache chaque point au
polygone qui le contient (`sjoin` / `within`) ; un point qui ne tombe dans aucun
polygone — imprécision GPS, trait de côte — est rattaché au polygone le plus
proche, distance calculée en projection métrique (UTM 38S) et non en degrés, et
signalé comme rattachement approximatif.

```bash
python -m pytest tests/ -q
```

## Pages publiques

`static/embed/` contient deux pages autonomes, destinées au public et à
l'intégration par `<iframe>` dans une autre application. Elles ne montrent ni
les pré-souscripteurs ni les indicateurs internes.

| Page | Contenu |
|---|---|
| `index.html` | carte et liste, filtres ville et catégorie |
| `tableau.html` | registre trié, filtres **région** et **type de marchand**, lien Google Maps par ligne — ni Leaflet ni tuiles |

Elles sont publiées par GitHub Pages depuis `main` — **ce sont les adresses à
diffuser**, elles ne demandent aucune connexion :

```
https://jejew03.github.io/carte-partenaire-eariary/static/embed/index.html
https://jejew03.github.io/carte-partenaire-eariary/static/embed/tableau.html
```

Streamlit les sert aussi lui-même (`enableStaticServing` dans
`.streamlit/config.toml`), sous `/app/static/embed/` ; l'application affiche
ces liens, le code à copier et un aperçu dans sa section « Pages publiques à
intégrer ». Tant que l'application reste privée, ces secondes adresses exigent
une connexion. Voir [`static/embed/README.md`](static/embed/README.md)
pour les paramètres d'URL, les messages `postMessage` et l'identité visuelle,
qui est **délibérément distincte** de celle de l'application interne.

La colonne « Région » du tableau ne vient pas du Sheet, dont la colonne
« Province » mélange villes et anciennes provinces : elle est déduite des
coordonnées par appartenance au polygone ADM1 de `data/geo/mdg_adm1.geojson`,
au moment où `static/embed/build.py` régénère l'instantané.

## Design

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
