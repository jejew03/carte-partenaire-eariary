# Registre des partenaires eAriary — pages à intégrer

Deux pages autonomes présentant les établissements qui acceptent eAriary,
destinées à être posées dans une autre application par une simple balise
`<iframe>`. Aucune dépendance à Streamlit, à Python au moment de l'affichage,
ni à un CDN.

| Page | Contenu | Poids réseau |
|---|---|---|
| `carte.html` | carte et liste, filtres ville et catégorie | Leaflet embarqué + tuiles |
| `tableau.html` | registre trié et filtrable par **région** et **type de marchand**, lien Google Maps par ligne | aucun (pas de carte) |

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

`tableau.html` ne charge ni Leaflet ni la moindre tuile : c'est la page à
préférer quand l'application hôte n'a pas besoin d'une carte, quand la
connexion est lente, ou quand la liste doit rester lisible au clavier et aux
lecteurs d'écran.

**Ni bordure ni coin arrondi autour du cadre.** L'intégration doit se lire
comme une section de l'application hôte, pas comme un encart rapporté : c'est
le cadre visible, plus que le contenu, qui fait dire « c'est une iframe ». Si
l'application affiche déjà son propre titre au-dessus, ajoutez `?header=0` pour
ne pas empiler deux titrailles.

Hauteur conseillée : **620 px** en vue mixte, 420 px suffisent pour
`view=carte`, **520 px** pour le tableau. La page occupe 100 % de la hauteur de
l'iframe ; c'est donc l'attribut `height` de l'iframe qui commande. Le tableau
défile à l'intérieur du cadre, en-têtes de colonnes figés.

Ouvrez [`demo.html`](demo.html) pour voir l'intégration, les variantes de
paramètres et les messages émis. La page doit être **servie en HTTP** : en
`file://`, les navigateurs bloquent la relecture du Sheet.

```bash
python3 -m http.server 8000    # depuis la racine du dépôt
# puis http://localhost:8000/partenaires/demo.html
```

## D'où viennent les données, et quand elles se mettent à jour

Tout part d'un seul endroit : le **Google Sheet** du registre. Personne n'a à
recopier quoi que ce soit — remplir une ligne dans la feuille suffit.

Deux chemins mènent du Sheet à la page, l'un rapide, l'autre sûr :

1. **Relecture en direct, dans le navigateur.** Chaque page interroge le Sheet
   à son ouverture, puis **toutes les cinq minutes** tant qu'elle reste
   affichée. Une ligne ajoutée à la feuille apparaît donc d'elle-même : le
   tableau se complète, un repère de plus se pose sur la carte, les effectifs
   des filtres se recalculent — sans que personne ne recharge la page.
2. **L'instantané embarqué** `assets/instantane.js`, versionné dans le dépôt et
   **régénéré toutes les heures** par
   [`.github/workflows/instantane-partenaires.yml`](../.github/workflows/instantane-partenaires.yml).
   Il s'affiche immédiatement, avant même que le réseau ait répondu, et reste
   la donnée servie si la relecture en direct n'aboutit pas.

La relecture en direct échoue silencieusement — Sheet redevenu privé, visiteur
hors ligne, politique de sécurité de l'hôte qui interdit `docs.google.com` — et
la page continue alors d'afficher l'instantané. C'est pour ce cas que le
workflow horaire existe : sans lui, la copie de secours vieillirait.

Rien n'est interrogé quand l'onglet est masqué : une iframe posée dans un
onglet d'arrière-plan n'appelle pas Google pour rien. Au retour du visiteur, la
relecture est immédiate si le dernier appel remonte à plus d'un intervalle.

Un rafraîchissement qui n'apporte rien de neuf ne redessine rien. Un qui
apporte des lignes **ne recadre pas la carte et ne défait pas la sélection** :
le visiteur peut avoir zoomé sur un quartier, et lui reprendre son cadrage
parce qu'une ligne a été ajoutée à l'autre bout de l'île serait insupportable.

### Régénérer l'instantané à la main

```bash
python3 partenaires/build.py            # relit le Sheet et réécrit l'instantané
python3 partenaires/build.py --check    # code de sortie 1 si l'instantané a vieilli
```

Le script n'utilise que la bibliothèque standard — pas besoin du virtualenv du
projet — et ne réécrit rien si la lecture échoue.

Le workflow tourne à la 17e minute de chaque heure et se déclenche aussi à la
demande, par le bouton « Run workflow » de l'onglet **Actions** : à utiliser
juste après une grosse saisie, plutôt que d'attendre l'heure suivante. Il ne
commite que si les données ont réellement changé — la seule date de génération
ne suffit pas à produire un commit.

> **À savoir** : GitHub suspend les workflows planifiés après 60 jours sans
> activité dans le dépôt, et le prévient par courriel. Un `git push`, ou un
> lancement manuel, les réactive.

## Colonnes du Google Sheet

Quatre colonnes sont attendues, retrouvées **par leur intitulé** et non par
leur position — les réordonner dans le Sheet ne casse rien :

| Colonne | Intitulés reconnus | Rôle |
|---|---|---|
| Ville | `Province`, `Ville`, `Région` | groupe la liste, remplit le filtre de ville |
| Nom | `Nom de l'établissement`, `Enseigne`, `Nom` | le libellé affiché |
| Type | `Catégorie`, `Type` | couleur, glyphe et filtre de catégorie |
| Coordonnées | `Latitude / longitude`, `Coord`, `GPS` | `-12.289942, 49.291381` |

### Colonnes facultatives

Quatre autres sont reconnues **si vous les ajoutez au Sheet**. Tant qu'elles
n'existent pas — ou tant qu'aucune ligne n'est remplie — les pages sont
exactement ce qu'elles sont aujourd'hui : aucune colonne vide, aucun champ
« non renseigné ».

| Colonne | Intitulés reconnus | Où elle apparaît |
|---|---|---|
| Téléphone | `Téléphone`, `Tél.`, `Mobile`, `WhatsApp`, `Contact` | colonne **Contact** du tableau (numéro cliquable), popup et fiche de la carte |
| Adresse | `Adresse`, `Quartier`, `Rue` | sous le nom dans le tableau, popup et fiche de la carte ; **entre aussi dans la recherche** |
| Horaires | `Horaires`, `Ouverture`, `Heures` | sous le nom dans le tableau, popup de la carte |
| Site | `Site`, `Web`, `URL`, `Facebook`, `Lien` | colonne **Contact** du tableau, popup de la carte |

La colonne « Contact » du tableau n'apparaît que si le Sheet porte au moins un
téléphone ou un site : une colonne vide dirait au public qu'on ne sait pas
joindre les partenaires. Adresse et horaires, eux, se placent sous le nom
plutôt qu'en colonnes — un registre de huit colonnes serait illisible dès le
premier écran étroit.

Aucune de ces colonnes n'est devinée par sa position : elle n'existe que si son
intitulé la nomme. Une colonne quelconque ne peut donc pas se retrouver
présentée comme un numéro de téléphone.

### Nettoyage appliqué

Mêmes règles que `load_data()` dans `app.py` : ligne d'en-tête détectée par le
mot « Province » (ou « Établissement »), colonnes retrouvées par mots-clés,
coordonnées lues au format `-12.289942, 49.291381`.

Deux corrections de libellés, appliquées à l'identique dans `build.py` et
`assets/donnees.js` :

- catégories : `Supermaché`/`Supermarche` → `Supermarché`, `Epicerie` →
  `Épicerie`, `Hotel` → `Hôtel` ;
- villes : `Antsirananana` → `Antsiranana`, `Fianaratsoa` → `Fianarantsoa`.
  L'application Streamlit, à usage interne, affiche ces fautes du Sheet telles
  quelles ; ces pages-ci s'adressant au public, elles les corrigent. **Le mieux
  reste de corriger le Sheet, puis de retirer ces deux entrées des deux
  fichiers.**

Un établissement dont la cellule de coordonnées n'est pas exploitable
(« Introuvable, quartier Amparihy ») **reste dans la liste**, avec la mention
« Coordonnées indisponibles » et la valeur brute ; il n'apparaît simplement pas
sur la carte. Le compteur distingue alors « n établissements — m sur la
carte » ; dans le tableau, « n établissements — m non localisés ».

### Région administrative

Le Sheet ne porte pas la région : sa colonne « Province » mélange des villes
(Tolagnaro, Sambava) et d'anciennes provinces (Mahajanga, Toamasina). Elle est
donc déduite des coordonnées, par appartenance au polygone **ADM1** de
`data/geo/mdg_adm1.geojson` — les mêmes limites que la choroplèthe de
l'application interne (BNGRC / OCHA, voir `data/geo/SOURCE.md`).

Le calcul est fait **par `build.py`** : le navigateur n'a ni les polygones ni de
quoi les parcourir. `build.py` dépose donc aussi dans l'instantané une table
`regions_par_ville`, dont les lignes relues en direct se servent pour se
rattacher par le libellé de leur ville. Conséquences à connaître :

- une **ville ajoutée au Sheet** depuis le dernier passage du workflow horaire
  s'affiche sous « Région à préciser » jusqu'à la régénération suivante ; sa
  ligne reste dans le tableau et le filtre la retrouve sous ce libellé ;
- un point qui ne tombe dans aucun polygone — trait de côte simplifié à
  ~880 m, saisie GPS approximative — rejoint la **région la plus proche** dans
  un rayon de 0,25° (~28 km), et reste sans région au-delà ;
- un établissement **sans coordonnée exploitable** hérite de la région de sa
  ville ;
- le millésime COD-AB 2018 compte **22 régions et non 23** : le découpage de
  2021, qui scinde Vatovavy Fitovinany, n'y est pas.

Si `data/geo/mdg_adm1.geojson` est absent, `build.py` le signale et génère
l'instantané sans région ; le tableau affiche alors partout « Région à
préciser » — il ne tombe pas en panne.

## Paramètres

Ils se passent dans l'URL de l'iframe : `carte.html?view=carte&header=0`.

| Paramètre | Valeurs | Défaut | Effet |
|---|---|---|---|
| `view` | `split`, `carte`, `liste` | `split` | carte + liste, carte seule, liste seule (page carte) |
| `header` | `1`, `0` | `1` | affiche ou masque la titraille et la note de source |
| `titre` | texte libre | — | remplace le titre par défaut |
| `theme` | `clair`, `sombre`, `auto` | `clair` | `auto` suit le thème du système du visiteur |
| `q` | texte | — | remplit la recherche au chargement |
| `live` | `1`, `0` | `1` | `0` fige la page sur l'instantané, sans aucun appel à Google |
| `refresh` | secondes, ou `0` | `300` | période de relecture du Sheet ; plancher à 60 s, `0` la désactive |
| `origin` | origine exacte | `*` | restreint la cible des `postMessage` |

Les valeurs contenant des accents ou des espaces doivent être encodées :
`categorie=Restaurant,H%C3%B4tel`.

### Propres à la carte

| Paramètre | Valeurs | Effet |
|---|---|---|
| `categorie` | catégories séparées par des virgules | présélectionne les puces (`Restaurant,Hôtel`) |
| `province` | une ville | présélectionne le filtre de ville |

Sous 860 px de large, la vue `split` se replie automatiquement en deux onglets
« Carte » / « Liste » — inutile de détecter le mobile côté hôte.

### Propres au tableau

| Paramètre | Valeurs | Défaut | Effet |
|---|---|---|---|
| `region` | une région | — | présélectionne le filtre de région (`Anosy`) |
| `categorie` | un type | — | présélectionne le filtre de type (`Restaurant`) |
| `ville` | une ville | — | restreint le tableau à cette ville, sans commande visible |
| `tri` | `nom`, `categorie`, `region`, `province` | `region` | colonne de tri au chargement |
| `sens` | `asc`, `desc` | `asc` | sens de ce tri |

`region` et `categorie` n'acceptent **qu'une valeur** — le tableau se lit comme
un registre, deux listes déroulantes y sont plus lisibles qu'une rangée de
puces. Une liste séparée par des virgules, le format de la page carte, est
acceptée sans erreur : seule la première valeur est retenue. `ville` n'a pas de
commande dans l'interface : c'est un cadrage posé par l'hôte, que le visiteur
ne peut pas défaire.

Sous 680 px de large, le tableau se replie en blocs — une fiche par
établissement, chaque champ précédé de son étiquette — plutôt que de se faire
pousser de gauche à droite.

## Dialogue avec l'application hôte

Les deux pages envoient des `postMessage` au parent, avec le même protocole.
Vérifiez toujours l'expéditeur :

```js
window.addEventListener("message", (event) => {
  if (event.origin !== "https://votre-domaine.example") return;
  if (!event.data || event.data.source !== "eariary-partenaires") return;

  switch (event.data.type) {
    case "pret":      /* { total, visibles, provenance } */ break;
    case "maj":       /* { total, visibles } — le Sheet a changé */ break;
    case "filtre":    /* voir ci-dessous — diffère d'une page à l'autre */ break;
    case "selection": /* { etablissement: { … } } */ break;
  }
});
```

| Message | Carte | Tableau |
|---|---|---|
| `pret` | `{ total, visibles, provenance }` — émis une seule fois | idem |
| `maj` | `{ total, visibles }` — à chaque relecture qui change les données | idem |
| `filtre` | `{ visibles, recherche, province, categories }` | `{ visibles, recherche, region, categorie, tri, sens }` |
| `selection` | émis au clic sur une fiche ou un repère | émis au clic sur un **nom** ; le lien Google Maps, lui, ouvre un onglet |

`selection.etablissement` porte toujours `nom, categorie, region, province,
lat, lon`, et les champs facultatifs (`adresse`, `horaires`, `telephone`,
`site`) **seulement quand le Sheet les renseigne**.

`provenance` vaut `"instantane"` ou `"direct"` selon que la page affiche la
copie embarquée ou le Sheet relu. Le champ ne s'appelle pas `source` : celui-ci
identifie l'iframe dans l'enveloppe du message, et une charge utile ne doit pas
pouvoir l'écraser.

Dans l'autre sens, l'hôte peut demander une relecture immédiate — par exemple
juste après avoir lui-même écrit dans le Sheet :

```js
iframe.contentWindow.postMessage(
  { source: "eariary-hote", type: "rafraichir" },
  "https://votre-domaine.example"
);
```

Seules des données publiques circulent. La cible par défaut est `*` ; passez
`?origin=https://votre-domaine.example` pour la restreindre à votre
application.

## Déploiement

### En ligne (GitHub Pages)

Les pages sont publiées à partir de la branche `main` :

```
https://jejew03.github.io/carte-partenaire-eariary/partenaires/carte.html
https://jejew03.github.io/carte-partenaire-eariary/partenaires/tableau.html
```

Ce sont **les URL à donner aux intégrateurs** : elles ne demandent aucune
authentification, contrairement à l'application Streamlit, qui est privée.
Chaque `git push` sur `main` republie les pages — le commit horaire du workflow
compris. Le fichier `.nojekyll` à la racine désactive Jekyll, qui filtrerait et
réécrirait les fichiers.

### Ailleurs

Copiez le dossier `partenaires/` tel quel sur n'importe quel hébergement
statique (Nginx, Apache, S3, Netlify, `public/` d'une application Laravel ou
Symfony, `static/` d'un projet Django…). Les chemins internes sont
**relatifs** : le dossier fonctionne à la racine comme dans un
sous-répertoire. Seul `build.py` remonte d'un cran, pour lire
`data/geo/mdg_adm1.geojson` ; il n'a pas à être déployé.

Si l'application hôte impose une politique de sécurité stricte, les seuls
domaines à autoriser sont ceux des fonds de carte (`basemaps.cartocdn.com`,
`tile.openstreetmap.org`, `server.arcgisonline.com`) et `docs.google.com` pour
la relecture en direct. Sans ce dernier, ajoutez `live=0` : la page servira
l'instantané, que le workflow horaire maintient à jour.

## Contenu du dossier

| Fichier | Rôle |
|---|---|
| `carte.html` | la page carte à mettre dans l'iframe |
| `tableau.html` | la page tableau à mettre dans l'iframe |
| `assets/theme.css` | thème, ossature, titraille, barre de filtres — commun aux deux pages |
| `assets/carte.css` | carte, liste latérale, retouches Leaflet |
| `assets/tableau.css` | le registre : colonnes, tri, repli en blocs |
| `assets/donnees.js` | lecture du Sheet, nettoyage, boucle de rafraîchissement |
| `assets/categories.js` | couleurs et glyphes des types de marchand, communs aux deux pages |
| `assets/carte.js` | carte, liste, filtres, sélection, messages |
| `assets/tableau.js` | tableau, tri, filtres région et type, messages |
| `assets/instantane.js` | copie embarquée des données (**généré** — ne pas modifier) |
| `vendor/leaflet/` | Leaflet 1.9.4 embarqué (BSD-2-Clause, `LICENSE` inclus) — page carte seule |
| `build.py` | régénère l'instantané depuis le Google Sheet |
| `demo.html` | page d'exemple d'intégration, pour les deux pages |

## Identité visuelle

Ces pages s'adressent au public, là où l'application Streamlit sert en interne.
Elles ont donc leur propre identité — institutionnelle et minimale, dans
l'esprit d'un registre officiel — plutôt que l'apparence par défaut d'un
composant web :

- **encre sur papier chaud**, pas de gris bleuté ; un seul accent (`#1a4066`),
  employé pour les liens, le focus et la fiche sélectionnée ;
- **filets d'un pixel** et angles vifs (rayon 2 px) au lieu de cartes,
  pastilles et ombres portées ;
- **titraille en romain à empattements** (familles présentes sur les systèmes,
  aucune police téléchargée), texte d'interface en `system-ui` ; étiquettes en
  petites capitales espacées ; chiffres et numéros en chasse fixe ;
- **la provenance des données est une note de bas de page**, pas un voyant
  d'état : « Source : registre des partenaires eAriary, mis à jour à 14:32 » ;
- **commandes de carte redessinées** (zoom, fonds, échelle, attribution) :
  Leaflet arrondit et ombre tout par défaut, ce qui jure avec le reste ;
- **repères circulaires** cernés de blanc, à la manière d'un symbole
  cartographique, plutôt que la goutte des applications de navigation ; le
  repère sélectionné grossit et prend un cercle d'encre ;
- **fond de carte accordé au thème** (CARTO clair ou sombre) ;
- aucun emoji, aucune animation décorative.

Le tableau suit les mêmes règles : filets d'un pixel et aucune alternance de
fond — un registre officiel se tient par ses filets et son alignement, pas par
des bandes colorées —, en-têtes de colonnes en petites capitales espacées et
figés en haut du cadre, sens du tri marqué par un chevron **et** par l'encre du
libellé, jamais par la couleur seule. Le lien Google Maps porte le nom du
service plutôt qu'une icône seule, et s'ouvre dans un nouvel onglet
(`rel="noopener"`) : il pointe sur les coordonnées, pas sur le nom, deux
enseignes pouvant se ressembler.

La palette de catégories (`assets/categories.js`, partagée par les deux pages)
reprend les teintes de `CATEGORY_STYLE` (`app.py`) mais les ramène à une clarté
et une saturation communes : les couleurs d'origine sont celles des marqueurs
par défaut de Leaflet, et elles se remarquent comme telles. **C'est la seule
divergence assumée avec l'application interne** — pour la supprimer, il suffit
de recopier les hex de `app.py` dans `assets/categories.js`.

Règles conservées :

- un glyphe SVG distinct par catégorie : **la couleur n'est jamais la seule
  information** ;
- une sélection de filtre vide équivaut à « tout afficher » ;
- les catégories servent de filtre **et** de légende, avec l'effectif de
  chacune ; le carré de couleur reste à pleine opacité même quand le filtre est
  inactif, la sélection se lisant au libellé et au filet qui le souligne. Dans
  le tableau, les listes déroulantes portent le même effectif entre
  parenthèses — filtrer et voir la répartition restent le même geste.

Accessibilité : liste navigable au clavier (chaque fiche est un `<button>`,
`aria-current` sur la fiche sélectionnée), libellés sur tous les champs,
contrastes conformes AA, thème sombre pris en charge, animations supprimées si
`prefers-reduced-motion` est actif. Le tableau est un vrai `<table>` —
`<th scope="col">`, légende pour lecteurs d'écran, `aria-sort` sur la colonne
de tri, en-têtes cliquables qui sont des `<button>` : il s'annonce et se
parcourt comme un tableau, y compris hors de la souris.

## Attribution

Fonds de carte : © OpenStreetMap, © CARTO, Esri — l'attribution est affichée
dans la carte et doit être conservée. Leaflet est distribué sous licence
BSD-2-Clause (`vendor/leaflet/LICENSE`).

## Rapport avec `static/embed/`

Ce dossier remplace `static/embed/`, dont il reprend le fond en le découpant
autrement : feuilles de style séparées (le tableau ne charge plus les styles
Leaflet), colonnes facultatives du Sheet, rafraîchissement périodique, et
instantané régénéré par un workflow plutôt qu'à la main. `static/embed/` reste
en place tant que des intégrateurs pointent sur ses URL ; il n'y a rien à y
faire, mais rien n'y arrive non plus — c'est ce dossier-ci qui est maintenu.
