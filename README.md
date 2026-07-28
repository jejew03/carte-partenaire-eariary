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

## Fonctionnalités

- Carte Folium avec clustering, marqueurs colorés par catégorie, fond satellite optionnel
- Popup par établissement + lien direct vers Google Maps
- Filtres : province/ville, catégorie, recherche par nom
- Tableau détaillé + export CSV de la sélection
- Section dédiée aux lignes dont les coordonnées ne sont pas exploitables

## Structure attendue du Sheet

| Province | Nom de l'établissement | Catégorie | Latitude / longitude |
|---|---|---|---|

La ligne d'en-tête est détectée automatiquement (celle contenant « Province »),
et les colonnes sont retrouvées par mots-clés — l'ordre exact n'est donc pas critique.
