# Page intégrable « Établissements partenaires eAriary »

Page autonome — carte **et** liste des établissements qui acceptent eAriary —
destinée à être intégrée dans une autre application par une simple balise
`<iframe>`. Aucune dépendance à Streamlit, à Python au runtime, ni à un CDN.

```html
<iframe
  src="/embed/index.html"
  title="Établissements partenaires eAriary"
  width="100%" height="620"
  style="display:block;border:0"
  loading="lazy"></iframe>
```

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

### Servie par l'application Streamlit (par défaut)

Le dossier vit sous `static/`, que Streamlit sert lui-même dès que
`enableStaticServing = true` dans `.streamlit/config.toml`. La page est donc
publiée **avec l'application, à la même adresse**, sans hébergement séparé :

```
https://<url-de-l-application>/app/static/embed/index.html
```

L'application affiche ce lien et le code à copier dans sa section « Page
publique à intégrer », en bas de page.

### Ailleurs

Copiez le dossier `static/embed/` tel quel sur n'importe quel hébergement
statique (Nginx, Apache, S3, Netlify, `public/embed/` d'une application Laravel
ou Symfony, `static/` d'un projet Django…). Les chemins internes sont
**relatifs** : le dossier fonctionne à la racine comme dans un
sous-répertoire.

Contenu :

| Fichier | Rôle |
|---|---|
| `index.html` | la page à mettre dans l'iframe |
| `assets/embed.css` | thème, mise en page, styles de la carte |
| `assets/embed.js` | carte, liste, filtres, sélection, messages |
| `assets/data.js` | lecture du Sheet et nettoyage des lignes |
| `assets/etablissements.js` | instantané des données (généré) |
| `vendor/leaflet/` | Leaflet 1.9.4 embarqué (BSD-2-Clause, `LICENSE` inclus) |
| `build.py` | régénère l'instantané depuis le Google Sheet |
| `demo.html` | page d'exemple d'intégration |

Hauteur conseillée : **620 px** minimum en vue mixte, 420 px suffisent pour
`view=carte`. La page occupe 100 % de la hauteur de l'iframe ; c'est donc
l'attribut `height` de l'iframe qui commande, pas la page.

## Paramètres

Ils se passent dans l'URL de l'iframe : `index.html?view=carte&header=0`.

| Paramètre | Valeurs | Défaut | Effet |
|---|---|---|---|
| `view` | `split`, `carte`, `liste` | `split` | carte + liste, carte seule, liste seule |
| `header` | `1`, `0` | `1` | affiche ou masque la titraille et la note de source |
| `titre` | texte libre | — | remplace le titre par défaut |
| `theme` | `auto`, `clair`, `sombre` | `auto` | `auto` suit le thème du système |
| `categorie` | catégories séparées par des virgules | — | présélectionne les puces (`Restaurant,Hôtel`) |
| `province` | une ville | — | présélectionne le filtre de ville |
| `q` | texte | — | remplit la recherche au chargement |
| `live` | `1`, `0` | `1` | `0` désactive la relecture du Sheet (instantané seul) |
| `origin` | origine exacte | `*` | restreint la cible des `postMessage` |

Les valeurs contenant des accents ou des espaces doivent être encodées :
`categorie=Restaurant,H%C3%B4tel`.

Sous 860 px de large, la vue `split` se replie automatiquement en deux onglets
« Carte » / « Liste » — inutile de détecter le mobile côté hôte.

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

## Dialogue avec l'application hôte

L'iframe envoie des `postMessage` au parent. Vérifiez toujours l'expéditeur :

```js
window.addEventListener("message", (event) => {
  if (event.origin !== "https://votre-domaine.example") return;
  if (!event.data || event.data.source !== "eariary-embed") return;

  switch (event.data.type) {
    case "pret":      /* { total, visibles, source } */ break;
    case "filtre":    /* { visibles, recherche, province, categories } */ break;
    case "selection": /* { etablissement: { nom, categorie, province, lat, lon } } */ break;
  }
});
```

Seules des données publiques circulent (nom, catégorie, ville, coordonnées).
La cible par défaut est `*` ; passez `?origin=https://votre-domaine.example`
pour la restreindre à votre application.

## Identité visuelle

Cette page s'adresse au public, là où l'application Streamlit sert en interne.
Elle a donc sa propre identité — institutionnelle et minimale, dans l'esprit
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

La palette de catégories reprend les teintes de `CATEGORY_STYLE` (`app.py`)
mais les ramène à une clarté et une saturation communes : les couleurs
d'origine sont celles des marqueurs par défaut de Leaflet, et elles se
remarquent comme telles. **C'est la seule divergence assumée avec
l'application interne** — pour la supprimer, il suffit de recopier les hex de
`app.py` dans `CATEGORIES` (`assets/embed.js`).

Règles conservées :

- un glyphe SVG distinct par catégorie : **la couleur n'est jamais la seule
  information** ;
- une sélection de filtre vide équivaut à « tout afficher » ;
- les catégories servent de filtre **et** de légende, avec l'effectif de
  chacune ; le carré de couleur reste à pleine opacité même quand le filtre
  est inactif, la sélection se lisant au libellé et au filet qui le souligne.

Accessibilité : liste navigable au clavier (chaque fiche est un `<button>`,
`aria-current` sur la fiche sélectionnée), libellés sur tous les champs,
contrastes conformes AA, thème sombre pris en charge, animations supprimées si
`prefers-reduced-motion` est actif.

## Attribution

Fonds de carte : © OpenStreetMap, © CARTO, Esri — l'attribution est affichée
dans la carte et doit être conservée. Leaflet est distribué sous licence
BSD-2-Clause (`vendor/leaflet/LICENSE`).
