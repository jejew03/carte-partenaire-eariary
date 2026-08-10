# Registre des partenaires eAriary — pages à intégrer

Deux pages autonomes listant les établissements qui acceptent eAriary,
destinées à être posées dans une autre application par une balise `<iframe>`.

Pas de framework, pas de build, pas de CDN, aucune dépendance à Streamlit :
du HTML, du CSS et du JavaScript ES5, plus Leaflet embarqué dans le dossier.
Il suffit de copier `partenaires/` sur un hébergement statique.

| Page | Contenu | Poids réseau |
|---|---|---|
| `carte.html` | carte et liste, filtres ville et catégorie | Leaflet + tuiles |
| `tableau.html` | registre triable, filtres région et type de marchand | aucun |

```html
<iframe
  src="/partenaires/carte.html"
  title="Établissements partenaires eAriary"
  width="100%" height="620"
  style="display:block;border:0"
  loading="lazy"></iframe>

<iframe
  src="/partenaires/tableau.html"
  title="Établissements partenaires eAriary"
  width="100%" height="520"
  style="display:block;border:0"
  loading="lazy"></iframe>
```

Hauteur conseillée : **620 px** pour la carte en vue mixte (420 px pour
`view=carte`), **520 px** pour le tableau. La page occupe 100 % de la hauteur
de l'iframe : c'est l'attribut `height` qui commande. Le tableau défile à
l'intérieur du cadre, en-têtes figés.

Si l'application hôte affiche déjà son propre titre au-dessus, ajoutez
`?header=0` pour ne pas empiler deux titrailles.

## Démarrage rapide

```bash
python3 -m http.server 8000    # depuis la racine du dépôt
# puis http://localhost:8000/partenaires/demo.html
```

`demo.html` montre l'intégration, les variantes de paramètres et les messages
échangés avec l'hôte. Servez la page en HTTP : en `file://`, les navigateurs
bloquent la lecture du Google Sheet.

## Architecture

```
partenaires/
├── carte.html              page carte : structure HTML seule
├── tableau.html            page tableau : structure HTML seule
├── demo.html               exemple d'intégration (hors production)
├── build.py                génère l'instantané depuis le Sheet
├── assets/
│   ├── theme.css           variables, thème, ossature, barre de filtres
│   ├── carte.css           carte, liste latérale, retouches Leaflet
│   ├── tableau.css         le registre
│   ├── categories.js       couleur + glyphe par catégorie   → EARIARY_CATEGORIES
│   ├── donnees.js          lecture du Sheet, rafraîchissement → EARIARY_DONNEES
│   ├── instantane.js       copie embarquée (GÉNÉRÉ)          → EARIARY_PARTENAIRES
│   ├── carte.js            logique de la page carte
│   └── tableau.js          logique de la page tableau
└── vendor/leaflet/         Leaflet 1.9.4 (BSD-2-Clause)
```

Trois variables globales, chargées dans cet ordre par les deux pages :
`EARIARY_PARTENAIRES` (les données embarquées), `EARIARY_CATEGORIES` (les
couleurs), `EARIARY_DONNEES` (l'accès au Sheet). `carte.js` et `tableau.js` ne
communiquent pas entre eux ; chacun ne connaît que sa page.

### Circulation des données

```
Google Sheet
   │
   ├── build.py ──────────► assets/instantane.js ──► affiché au chargement
   │   (workflow horaire)                            (copie de secours)
   │
   └── donnees.js ────────────────────────────────► remplace l'instantané
       (fetch dans le navigateur, toutes les 5 min)
```

`build.py` et `donnees.js` appliquent **les mêmes règles de lecture** : même
détection d'en-tête, mêmes mots-clés de colonnes, même format de coordonnées,
mêmes corrections de libellés. Toute modification de l'un doit être reportée
dans l'autre.

## Mise à jour des données

Tout part du **Google Sheet**. Remplir une ligne suffit ; il n'y a rien à
recopier ailleurs.

**1. Relecture en direct.** Chaque page interroge le Sheet à son ouverture,
puis toutes les 5 minutes tant qu'elle reste affichée. Une ligne ajoutée
apparaît d'elle-même : le tableau se complète, un repère se pose sur la carte,
les effectifs des filtres se recalculent — sans rechargement.

- Rien n'est appelé quand l'onglet est masqué. Au retour du visiteur, une
  relecture est déclenchée si le dernier appel date de plus d'un intervalle.
- Une relecture qui ne change rien ne redessine rien (comparaison par
  empreinte, `EARIARY_DONNEES.signature`).
- Une relecture qui apporte des lignes **ne recadre pas la carte et ne défait
  pas la sélection** : la fiche sélectionnée est retrouvée par une clé stable
  (nom + ville + coordonnées) et non par son numéro de ligne, qui se décale dès
  qu'on insère une ligne dans la feuille.
- Un échec est silencieux : la page garde ce qu'elle affiche.

**2. Instantané embarqué.** `assets/instantane.js` est versionné dans le dépôt
et régénéré chaque heure par
[`.github/workflows/instantane-partenaires.yml`](../.github/workflows/instantane-partenaires.yml).
Il s'affiche avant que le réseau réponde, et reste la donnée servie si la
relecture en direct échoue — feuille redevenue privée, visiteur hors ligne,
application hôte interdisant `docs.google.com`.

### Régénérer l'instantané à la main

```bash
python3 partenaires/build.py            # relit le Sheet et réécrit le fichier
python3 partenaires/build.py --check    # code de sortie 1 si le fichier a vieilli
```

Bibliothèque standard uniquement : aucune installation, pas besoin du
virtualenv du projet. Le script ne réécrit rien si la lecture échoue.

Le workflow tourne à la 17e minute de chaque heure et se déclenche aussi à la
demande (onglet **Actions** → **Run workflow**). Il ne commite que si les
données ont réellement changé : la seule date de génération ne produit pas de
commit.

> **À savoir** : GitHub suspend les workflows planifiés après 60 jours sans
> activité dans le dépôt, et le signale par courriel. Un `git push` ou un
> lancement manuel les réactive.

## Colonnes du Google Sheet

Les colonnes sont retrouvées **par leur intitulé**, pas par leur position : les
réordonner dans le Sheet ne casse rien. La ligne d'en-tête est repérée par le
mot « Province » ou « Établissement », ce qui autorise un titre au-dessus.

### Obligatoires

| Colonne | Intitulés reconnus | Rôle |
|---|---|---|
| Ville | `Province`, `Ville`, `Région` | groupe la liste, remplit le filtre de ville |
| Nom | `Nom de l'établissement`, `Enseigne`, `Nom` | le libellé affiché |
| Type | `Catégorie`, `Type` | couleur, glyphe et filtre de catégorie |
| Coordonnées | `Latitude / longitude`, `Coord`, `GPS` | format `-12.289942, 49.291381` |

Si aucun intitulé ne correspond, ces quatre colonnes retombent sur les
positions 1 à 4.

### Facultatives

Reconnues **si vous les ajoutez au Sheet**. Tant qu'elles n'existent pas — ou
tant qu'aucune ligne n'est remplie — les pages sont inchangées : ni colonne
vide, ni mention « non renseigné ».

| Colonne | Intitulés reconnus | Où elle apparaît |
|---|---|---|
| Téléphone | `Téléphone`, `Tél.`, `Mobile`, `WhatsApp`, `Contact` | colonne **Contact** du tableau (numéro cliquable), popup et fiche de la carte |
| Adresse | `Adresse`, `Quartier`, `Rue` | sous le nom dans le tableau, popup et fiche de la carte ; **entre aussi dans la recherche** |
| Horaires | `Horaires`, `Ouverture`, `Heures` | sous le nom dans le tableau, popup de la carte |
| Site | `Site`, `Web`, `URL`, `Facebook`, `Lien` | colonne **Contact** du tableau, popup de la carte |

Ces colonnes n'ont pas de position de repli : elles ne sont reconnues que par
leur intitulé, pour qu'une colonne quelconque ne soit jamais présentée comme un
numéro de téléphone.

La colonne « Contact » du tableau n'apparaît que si au moins un téléphone ou un
site est renseigné. Adresse et horaires se placent sous le nom plutôt qu'en
colonnes : à six colonnes, le tableau déborde dès le premier écran étroit.

### Nettoyage appliqué

Deux tables de correction, présentes à l'identique dans `build.py` et
`assets/donnees.js` :

- catégories : `Supermaché`/`Supermarche` → `Supermarché`, `Epicerie` →
  `Épicerie`, `Hotel` → `Hôtel` ;
- villes : `Antsirananana` → `Antsiranana`, `Fianaratsoa` → `Fianarantsoa`.

**Le mieux reste de corriger le Sheet, puis de vider ces deux tables dans les
deux fichiers.**

Une fiche dont la cellule de coordonnées est inexploitable
(« Introuvable, quartier Amparihy ») **reste dans la liste**, avec la mention
« Coordonnées indisponibles » et la valeur brute ; elle n'apparaît simplement
pas sur la carte. Le compteur le signale : « n établissements — m sur la
carte », et « n établissements — m non localisés » dans le tableau.

### Région administrative

Le Sheet ne contient pas la région : sa colonne « Province » mélange des villes
(Tolagnaro, Sambava) et d'anciennes provinces (Mahajanga, Toamasina). La région
est déduite des coordonnées, par appartenance aux polygones **ADM1** de
`data/geo/mdg_adm1.geojson` (source : BNGRC / OCHA, voir `data/geo/SOURCE.md`).

Le calcul est fait **par `build.py`** : les polygones pèsent plusieurs
mégaoctets, le navigateur ne les charge pas. `build.py` dépose donc aussi dans
l'instantané une table `regions_par_ville`, que les lignes relues en direct
utilisent pour se rattacher par le libellé de leur ville. À savoir :

- une **ville ajoutée au Sheet** depuis le dernier passage du workflow apparaît
  sous « Région à préciser » jusqu'à la régénération suivante ; sa ligne reste
  dans le tableau et le filtre la retrouve sous ce libellé ;
- un point hors de tout polygone — côte simplifiée, saisie GPS approximative —
  rejoint la **région la plus proche** dans un rayon de 0,25° (~28 km), et
  reste sans région au-delà ;
- une fiche **sans coordonnées** hérite de la région de sa ville ;
- le millésime COD-AB 2018 compte **22 régions et non 23** : le découpage de
  2021, qui scinde Vatovavy Fitovinany, n'y figure pas.

Si `data/geo/mdg_adm1.geojson` est absent, `build.py` le signale et génère
l'instantané sans région ; les pages affichent alors « Région à préciser »
partout, sans tomber en panne.

## Paramètres d'URL

Ils se passent dans l'URL de l'iframe : `carte.html?view=carte&header=0`.
Les valeurs accentuées doivent être encodées : `categorie=Restaurant,H%C3%B4tel`.

### Communs aux deux pages

| Paramètre | Valeurs | Défaut | Effet |
|---|---|---|---|
| `header` | `1`, `0` | `1` | affiche ou masque la titraille |
| `titre` | texte libre | — | remplace le titre par défaut |
| `theme` | `clair`, `sombre`, `auto` | `clair` | `auto` suit le thème du système du visiteur |
| `q` | texte | — | remplit la recherche au chargement |
| `live` | `1`, `0` | `1` | `0` fige la page sur l'instantané, sans aucun appel à Google |
| `refresh` | secondes, ou `0` | `300` | période de relecture du Sheet ; plancher à 60 s, `0` la désactive |
| `origin` | origine exacte | `*` | restreint la cible des `postMessage` |

### Page carte

| Paramètre | Valeurs | Défaut | Effet |
|---|---|---|---|
| `view` | `split`, `carte`, `liste` | `split` | carte + liste, carte seule, liste seule |
| `categorie` | catégories séparées par des virgules | — | présélectionne les puces |
| `province` | une ville | — | présélectionne le filtre de ville |

Sous 860 px de large, la vue `split` se replie en deux onglets « Carte » /
« Liste » : inutile de détecter le mobile côté hôte.

### Page tableau

| Paramètre | Valeurs | Défaut | Effet |
|---|---|---|---|
| `region` | une région | — | présélectionne le filtre de région (`Anosy`) |
| `categorie` | un type | — | présélectionne le filtre de type (`Restaurant`) |
| `ville` | une ville | — | restreint le tableau à cette ville, sans commande visible |
| `tri` | `nom`, `region`, `province`, `categorie` | `region` | colonne de tri au chargement |
| `sens` | `asc`, `desc` | `asc` | sens de ce tri |

`region` et `categorie` n'acceptent qu'**une seule valeur** : deux listes
déroulantes sont plus lisibles qu'une rangée de puces dans un registre. Une
liste séparée par des virgules est acceptée sans erreur, seule la première
valeur est retenue. `ville` n'a pas de commande dans l'interface : c'est un
cadrage posé par l'hôte, que le visiteur ne peut pas défaire.

Sous 680 px de large, le tableau se replie en blocs — une fiche par
établissement, chaque champ précédé de son étiquette.

## Messages échangés avec l'application hôte

### De l'iframe vers l'hôte

```js
window.addEventListener("message", (event) => {
  if (event.origin !== "https://votre-domaine.example") return;
  if (!event.data || event.data.source !== "eariary-partenaires") return;

  switch (event.data.type) {
    case "pret":      /* { total, visibles, provenance } */ break;
    case "maj":       /* { total, visibles } */ break;
    case "filtre":    /* voir le tableau ci-dessous */ break;
    case "selection": /* { etablissement: { … } } */ break;
  }
});
```

| Type | Quand | Charge utile |
|---|---|---|
| `pret` | une fois, au premier affichage | `{ total, visibles, provenance }` |
| `maj` | à chaque relecture qui change les données | `{ total, visibles }` |
| `filtre` | à chaque changement de filtre | carte : `{ visibles, recherche, province, categories }`<br>tableau : `{ visibles, recherche, region, categorie, tri, sens }` |
| `selection` | clic sur une fiche ou un repère (carte), sur un nom (tableau) | `{ etablissement }` |

`selection.etablissement` porte toujours `nom, categorie, region, province,
lat, lon`, et les champs facultatifs (`adresse`, `horaires`, `telephone`,
`site`) seulement lorsqu'ils sont renseignés.

`provenance` vaut `"instantane"` ou `"direct"` selon la source affichée. Ce
champ ne s'appelle pas `source` : `source` identifie l'iframe dans l'enveloppe
du message, et une charge utile ne doit pas pouvoir l'écraser.

### De l'hôte vers l'iframe

Forcer une relecture immédiate, par exemple après avoir écrit dans le Sheet :

```js
iframe.contentWindow.postMessage(
  { source: "eariary-hote", type: "rafraichir" },
  "https://votre-domaine.example"
);
```

Seules des données publiques circulent. La cible par défaut est `*` ; passez
`?origin=https://votre-domaine.example` pour la restreindre.

## Déploiement

### GitHub Pages (en place)

Publié depuis la branche `main`, à la racine :

```
https://jejew03.github.io/carte-partenaire-eariary/partenaires/carte.html
https://jejew03.github.io/carte-partenaire-eariary/partenaires/tableau.html
```

Ce sont les URL à donner aux intégrateurs : elles ne demandent aucune
authentification, contrairement à l'application Streamlit interne. Chaque
`git push` sur `main` republie les pages, y compris le commit horaire du
workflow. Le fichier `.nojekyll` à la racine désactive Jekyll.

### Ailleurs

Copiez `partenaires/` tel quel sur n'importe quel hébergement statique (Nginx,
Apache, S3, Netlify, `public/` d'une application Laravel ou Symfony, `static/`
d'un projet Django…). Les chemins internes sont **relatifs** : le dossier
fonctionne à la racine comme dans un sous-répertoire.

`build.py` n'a pas à être déployé : c'est un outil de génération, et il lit
`../data/geo/mdg_adm1.geojson`, hors du dossier.

### Politique de sécurité de l'hôte

Domaines à autoriser :

| Domaine | Pour quoi | Requis |
|---|---|---|
| `basemaps.cartocdn.com` | fond de carte par défaut | page carte |
| `tile.openstreetmap.org` | fond « Plan détaillé » | page carte |
| `server.arcgisonline.com` | fond « Satellite » | page carte |
| `docs.google.com` | relecture du Sheet | les deux pages |

Sans `docs.google.com`, ajoutez `live=0` : les pages serviront l'instantané,
que le workflow horaire maintient à jour.

## Conventions de code

- **JavaScript ES5** (`var`, pas de classes, pas de `let`/`const`) : ces pages
  sont intégrées dans des applications tierces dont on ne maîtrise pas le parc
  de navigateurs. Aucun transpileur, aucune étape de build.
- **Un fichier = une responsabilité.** `donnees.js` ne connaît pas le DOM ;
  `carte.js` et `tableau.js` ne connaissent pas le CSV.
- **Toute valeur venant du Sheet passe par `echapper()`** avant d'être insérée
  en HTML.
- **Nommage en français**, comme le reste du dépôt.
- La couleur ne porte jamais seule une information : chaque catégorie a son
  glyphe, le sens du tri se lit au chevron autant qu'à l'encre du libellé.
- Une sélection de filtre vide équivaut à « tout afficher ».

### Accessibilité

Chaque fiche de la liste est un `<button>`, avec `aria-current` sur la fiche
sélectionnée. Le tableau est un vrai `<table>` : `<th scope="col">`, légende
pour lecteurs d'écran, `aria-sort` sur la colonne de tri, en-têtes cliquables
qui sont des `<button>`. Tous les champs ont un libellé, les contrastes sont
conformes AA, le thème sombre est pris en charge, et les transitions sont
supprimées si `prefers-reduced-motion` est actif.

### Retouches à connaître avant de modifier le style

- `theme.css` porte les variables ; ne redéfinissez pas une couleur ailleurs.
- Les commandes de Leaflet sont redessinées dans `carte.css` (angles vifs,
  filets d'un pixel) ; Leaflet arrondit et ombre tout par défaut.
- Le repère de carte est un SVG généré dans `carte.js` (fonction `icone`), pas
  une image : sa couleur et son glyphe viennent de `categories.js`.

## Attribution

Fonds de carte : © OpenStreetMap, © CARTO, Esri — l'attribution est affichée
dans la carte et doit être conservée. Leaflet est distribué sous licence
BSD-2-Clause (`vendor/leaflet/LICENSE`).

## Historique

Ce dossier remplace `static/embed/`, supprimé du dépôt. Il en reprend le fond
avec un découpage différent : feuilles de style séparées (le tableau ne charge
plus les styles Leaflet), colonnes facultatives du Sheet, rafraîchissement
périodique, et instantané régénéré par un workflow plutôt qu'à la main.

Les anciennes adresses `…/static/embed/index.html` et
`…/static/embed/tableau.html` **ne répondent plus**. Un intégrateur qui les
utilise encore doit passer à `…/partenaires/carte.html` et
`…/partenaires/tableau.html` — noter le renommage de `index.html` en
`carte.html`.
