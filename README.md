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

## Fonctionnalités

- Carte Folium avec clustering, marqueurs colorés par catégorie, fonds
  interchangeables (plan clair par défaut, plan détaillé, satellite)
- Popup par établissement + lien direct vers Google Maps
- Couche « Pré-souscripteurs eAriary » : un cercle par localité, d'aire
  proportionnelle au nombre d'inscrits, avec la répartition par type de compte
  (aucune donnée nominative n'atteint la carte)
- Filtres : province/ville, catégorie, recherche par nom ; région et type de
  compte pour les pré-souscripteurs
- Tableau détaillé + export CSV de la sélection, récapitulatif par localité
  des pré-souscripteurs + export
- Sections dédiées aux lignes dont les coordonnées ne sont pas exploitables

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
