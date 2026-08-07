# Pages intégrables « Établissements partenaires eAriary »

Pages autonomes présentant les établissements qui acceptent eAriary, destinées
à être intégrées dans une autre application par une simple balise `<iframe>`.
Aucune dépendance à Streamlit, à Python au runtime, ni à un CDN.

Deux pages, mêmes données, même identité — à intégrer au choix, ou l'une sous
l'autre :

| Page | Contenu | Poids réseau |
|---|---|---|
| `index.html` | carte et liste, filtres ville et catégorie | Leaflet + tuiles |
| `tableau.html` | registre trié et filtrable par **région** et **type de marchand**, lien Google Maps par ligne | aucun (pas de carte) |

```html
<iframe
  src="/embed/index.html"
  title="Établissements partenaires eAriary"
  width="100%" height="620"
  style="display:block;border:0"
  loading="lazy"></iframe>

<iframe
  src="/embed/tableau.html"
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
l'application affiche déjà son propre titre au-dessus, ajoutez `?header=0`
pour ne pas empiler deux titrailles : une page dans une page se repère
immédiatement.

Ouvrez [`demo.html`](demo.html) pour voir l'intégration, les variantes de
paramètres et les messages émis. La page a besoin d'être **servie en HTTP** :
en `file://`, les navigateurs bloquent la relecture du Sheet.

```bash
python -m http.server 8000    # depuis la racine du dépôt
# puis http://localhost:8000/embed/demo.html
```

## Déploiement

### En ligne (GitHub Pages)

Les pages sont publiées à partir de la branche `main` du dépôt :

```
https://jejew03.github.io/carte-partenaire-eariary/static/embed/index.html
https://jejew03.github.io/carte-partenaire-eariary/static/embed/tableau.html
```

Ce sont **les URL à donner aux intégrateurs** : elles ne demandent aucune
authentification, contrairement à l'application Streamlit, qui est privée.
Chaque `git push` sur `main` republie les pages. Le fichier `.nojekyll` à la
racine désactive Jekyll, qui filtrerait et réécrirait les fichiers.

### Servie par l'application Streamlit

Le dossier vit sous `static/`, que Streamlit sert lui-même dès que
`enableStaticServing = true` dans `.streamlit/config.toml`. Les pages sont donc
aussi disponibles **à l'adresse de l'application** :

```
https://<url-de-l-application>/app/static/embed/index.html
https://<url-de-l-application>/app/static/embed/tableau.html
```

L'application affiche ce lien et le code à copier dans sa section « Page
publique à intégrer », en bas de page. Tant que l'application reste privée,
cette adresse-là exige une connexion : c'est un aperçu pour l'équipe, pas le
lien à diffuser.

### Ailleurs

Copiez le dossier `static/embed/` tel quel sur n'importe quel hébergement
statique (Nginx, Apache, S3, Netlify, `public/embed/` d'une application Laravel
ou Symfony, `static/` d'un projet Django…). Les chemins internes sont
**relatifs** : le dossier fonctionne à la racine comme dans un
sous-répertoire.

Contenu :

| Fichier | Rôle |
|---|---|
| `index.html` | la page carte à mettre dans l'iframe |
| `tableau.html` | la page tableau à mettre dans l'iframe |
| `assets/embed.css` | thème, mise en page, styles de la carte — commun aux deux pages |
| `assets/tableau.css` | le registre : colonnes, tri, repli en blocs |
| `assets/embed.js` | carte, liste, filtres, sélection, messages |
| `assets/tableau.js` | tableau, tri, filtres région et type, messages |
| `assets/categories.js` | couleurs et glyphes des types de marchand, communs aux deux pages |
| `assets/data.js` | lecture du Sheet et nettoyage des lignes |
| `assets/etablissements.js` | instantané des données (généré) |
| `vendor/leaflet/` | Leaflet 1.9.4 embarqué (BSD-2-Clause, `LICENSE` inclus) — carte seule |
| `build.py` | régénère l'instantané depuis le Google Sheet |
| `demo.html` | page d'exemple d'intégration, pour les deux pages |

Hauteur conseillée : **620 px** minimum en vue mixte, 420 px suffisent pour
`view=carte`, **520 px** pour le tableau. La page occupe 100 % de la hauteur de
l'iframe ; c'est donc l'attribut `height` de l'iframe qui commande, pas la
page. Le tableau défile à l'intérieur du cadre, en-têtes de colonnes figés.

## Paramètres

Ils se passent dans l'URL de l'iframe : `index.html?view=carte&header=0`.

| Paramètre | Valeurs | Défaut | Effet |
|---|---|---|---|
| `view` | `split`, `carte`, `liste` | `split` | carte + liste, carte seule, liste seule |
| `header` | `1`, `0` | `1` | affiche ou masque la titraille et la note de source |
| `titre` | texte libre | — | remplace le titre par défaut |
| `theme` | `clair`, `sombre`, `auto` | `clair` | `auto` suit le thème du système du visiteur |
| `categorie` | catégories séparées par des virgules | — | présélectionne les puces (`Restaurant,Hôtel`) |
| `province` | une ville | — | présélectionne le filtre de ville |
| `q` | texte | — | remplit la recherche au chargement |
| `live` | `1`, `0` | `1` | `0` désactive la relecture du Sheet (instantané seul) |
| `origin` | origine exacte | `*` | restreint la cible des `postMessage` |

Les valeurs contenant des accents ou des espaces doivent être encodées :
`categorie=Restaurant,H%C3%B4tel`.

Sous 860 px de large, la vue `split` se replie automatiquement en deux onglets
« Carte » / « Liste » — inutile de détecter le mobile côté hôte.

### Propres au tableau

`header`, `titre`, `theme`, `q`, `live` et `origin` s'y comportent à
l'identique ; `view` n'a pas de sens ici. S'y ajoutent :

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

## Données

Deux sources, dans cet ordre :

1. **l'instantané** `assets/etablissements.js`, versionné, affiché
   immédiatement ;
2. **le Google Sheet**, relu dans le navigateur (endpoint `gviz`, qui répond
   avec les en-têtes CORS nécessaires) et qui remplace l'instantané dès qu'il
   répond — la note de source en pied de page passe alors de « relevé du
   *date* » à « consulté à l'instant ».

Un échec de l'étape 2 (Sheet repassé en privé, hors ligne, CSP de l'hôte qui
interdit `docs.google.com`) est silencieux : la liste reste celle de
l'instantané. Pour régénérer celui-ci :

```bash
python static/embed/build.py            # relit le Sheet et réécrit l'instantané
python static/embed/build.py --check    # code de sortie 1 si l'instantané a vieilli
```

Le script n'utilise que la bibliothèque standard — pas besoin du virtualenv du
projet — et ne réécrit rien si la lecture échoue.

Si l'application hôte impose une politique de sécurité stricte, les seuls
domaines à autoriser sont ceux des fonds de carte
(`basemaps.cartocdn.com`, `tile.openstreetmap.org`,
`server.arcgisonline.com`) et `docs.google.com` pour la relecture en direct.
Sans ce dernier, ajoutez `live=0` et régénérez l'instantané à chaque
déploiement.

### Nettoyage appliqué

Mêmes règles que `load_data()` dans `app.py` : ligne d'en-tête détectée par le
mot « Province », colonnes retrouvées par mots-clés (l'ordre des colonnes du
Sheet n'est donc pas critique), coordonnées lues au format
`-12.289942, 49.291381`.

Deux corrections de libellés, appliquées à l'identique dans `build.py` et
`assets/data.js` :

- catégories : `Supermaché`/`Supermarche` → `Supermarché`, `Epicerie` →
  `Épicerie`, `Hotel` → `Hôtel` (comme dans `app.py`) ;
- provinces : `Antsirananana` → `Antsiranana`, `Fianaratsoa` →
  `Fianarantsoa`. L'application Streamlit, à usage interne, affiche ces deux
  fautes du Sheet telles quelles ; l'iframe étant destinée au public, elle les
  corrige. **Le mieux reste de corriger le Sheet, puis de retirer ces deux
  entrées des deux fichiers.**

Un établissement dont la cellule de coordonnées n'est pas exploitable
(« Introuvable, quartier Amparihy ») **reste dans la liste**, avec la mention
« Coordonnées indisponibles » et la valeur brute ; il n'apparaît simplement pas
sur la carte. Le compteur distingue alors « n établissements — m sur la carte ».
Le tableau applique la même règle : la ligne est là, sa colonne
« Localisation » indique « Non localisé » et donne la valeur brute du Sheet en
infobulle, et le compteur dit « n établissements — m non localisés ».

### Région administrative

Le Sheet ne porte pas la région : sa colonne « Province » mélange des villes
(Tolagnaro, Sambava) et d'anciennes provinces (Mahajanga, Toamasina). Le
tableau la déduit donc des coordonnées, par appartenance au polygone **ADM1**
de `data/geo/mdg_adm1.geojson` — les mêmes limites que la choroplèthe de
l'application interne (BNGRC / OCHA, voir `data/geo/SOURCE.md`).

Le calcul est fait **par `build.py`**, au moment de l'instantané : le
navigateur n'a ni les polygones ni de quoi les parcourir. `build.py` dépose
donc aussi dans l'instantané une table `regions_par_ville`, dont les lignes
relues en direct du Sheet se servent pour se rattacher par le libellé de leur
ville. Conséquences à connaître :

- une **ville ajoutée au Sheet** depuis le dernier `build.py` s'affiche sous
  « Région à préciser » jusqu'à la régénération de l'instantané ; sa ligne
  reste dans le tableau et le filtre la retrouve sous ce libellé ;
- un point qui ne tombe dans aucun polygone — trait de côte simplifié à
  ~880 m, saisie GPS approximative — est rattaché à la **région la plus
  proche** dans un rayon de 0,25° (~28 km), et laissé sans région au-delà ;
- un établissement **sans coordonnée exploitable** hérite de la région de sa
  ville ;
- le millésime COD-AB 2018 compte **22 régions et non 23** : le découpage de
  2021, qui scinde Vatovavy Fitovinany, n'y est pas.

Si `data/geo/mdg_adm1.geojson` est absent, `build.py` le signale et génère
l'instantané sans région ; le tableau affiche alors partout « Région à
préciser » — il ne tombe pas en panne.

## Dialogue avec l'application hôte

Les deux pages envoient des `postMessage` au parent, avec le même protocole.
Vérifiez toujours l'expéditeur :

```js
window.addEventListener("message", (event) => {
  if (event.origin !== "https://votre-domaine.example") return;
  if (!event.data || event.data.source !== "eariary-embed") return;

  switch (event.data.type) {
    case "pret":      /* { total, visibles, provenance } */ break;
    case "filtre":    /* voir ci-dessous — diffère d'une page à l'autre */ break;
    case "selection": /* { etablissement: { nom, categorie, province, lat, lon } } */ break;
  }
});
```

| Message | Carte | Tableau |
|---|---|---|
| `filtre` | `{ visibles, recherche, province, categories }` | `{ visibles, recherche, region, categorie, tri, sens }` |
| `selection` | émis au clic sur une fiche ou un repère | émis au clic sur un **nom** ; le lien Google Maps, lui, ouvre un onglet |
| `selection.etablissement` | `nom, categorie, province, lat, lon` | idem, plus `region` |

`provenance` vaut `"instantane"` ou `"direct"` selon que la page affiche la
copie embarquée ou le Sheet relu. **Ce champ s'appelait `source` jusqu'ici :
il écrasait alors le `source: "eariary-embed"` de l'enveloppe, de sorte que le
message `pret` n'arrivait jamais chez un hôte suivant le contrôle
d'expéditeur ci-dessus.** Un hôte qui lisait `event.data.source` sur `pret`
n'en tirait donc que `"eariary-embed"` ; il n'y a rien à migrer, seulement un
champ à lire désormais.

Seules des données publiques circulent (nom, catégorie, région, ville,
coordonnées). La cible par défaut est `*` ; passez
`?origin=https://votre-domaine.example` pour la restreindre à votre
application.

## Identité visuelle

Ces pages s'adressent au public, là où l'application Streamlit sert en interne.
Elles ont donc leur propre identité — institutionnelle et minimale, dans l'esprit
d'un registre officiel — plutôt que l'apparence par défaut d'un composant web :

- **encre sur papier chaud**, pas de gris bleuté ; un seul accent
  (`#1a4066`), employé pour les liens, le focus et la fiche sélectionnée ;
- **filets d'un pixel** et angles vifs (rayon 2 px) au lieu de cartes,
  pastilles et ombres portées ;
- **titraille en romain à empattements** (familles présentes sur les systèmes,
  aucune police téléchargée), texte d'interface en `system-ui` ; libellés de
  section en petites capitales espacées ; chiffres en chasse fixe ;
- **la provenance des données est une note de bas de page**, pas un voyant
  d'état : « Source : registre des partenaires eAriary, relevé du … » ;
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
  chacune ; le carré de couleur reste à pleine opacité même quand le filtre
  est inactif, la sélection se lisant au libellé et au filet qui le souligne.
  Dans le tableau, les listes déroulantes portent le même effectif entre
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
