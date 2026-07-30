# Limites administratives de Madagascar — provenance des données

Ce répertoire contient les seules données géographiques de l'application. Elles
sont **embarquées dans le dépôt** : l'application ne télécharge rien à
l'exécution. Elles sont produites uniquement par `tools/fetch_boundaries.py`,
qui est le seul point du projet accédant au réseau.

| Fichier | Niveau | Zones | Taille |
| --- | --- | --- | --- |
| `mdg_adm1.geojson` | Région | 22 | 0,491 Mo |
| `mdg_adm2.geojson` | District | 119 | 0,910 Mo |
| `mdg_adm3.geojson` | Commune | 1 579 | 1,442 Mo |
| `zones.csv` | les trois réunis | 1 720 | 0,089 Mo |

---

## Source retenue

**HDX / OCHA — « Madagascar - Subnational Administrative Boundaries »**
(Common Operational Dataset — Administrative Boundaries, *COD-AB*)

| | |
| --- | --- |
| Jeu de données | <https://data.humdata.org/dataset/cod-ab-mdg> |
| Ressource utilisée | `mdg_adm_bngrc_ocha_20181031_shp.zip` (shapefiles ADM0 à ADM4, 66,3 Mo) |
| Producteur des limites | Bureau National de Gestion des Risques et des Catastrophes (BNGRC), Madagascar |
| Publication / nettoyage | OCHA Field Information Services Section (FISS) |
| Vérification | Information Technology Outreach Services (ITOS) |
| Millésime des limites | 2018-10-31 (revu pour exactitude en mars 2024) |
| Publication HDX | 2020-02-20 |
| **Date de récupération** | **2026-07-30** |
| CRS d'origine | EPSG:4326 (WGS 84), conservé tel quel |

### Licence

**Creative Commons Attribution 3.0 IGO (CC BY 3.0 IGO)**
<http://creativecommons.org/licenses/by/3.0/igo/legalcode>

Redistribution, modification et usage commercial autorisés, à la seule condition
de citer la source. La simplification des géométries réalisée ici constitue une
œuvre dérivée, ce que la licence permet explicitement.

### Attribution exacte à afficher

Mention à faire figurer dans l'interface (pied de carte ou mention légale),
telle quelle :

> Limites administratives : BNGRC / OCHA, *Madagascar – Subnational
> Administrative Boundaries* (COD-AB, 2018-10-31), via HDX — CC BY 3.0 IGO.

Version courte, si la place manque :

> Limites : BNGRC / OCHA via HDX (CC BY 3.0 IGO)

---

## Sources testées et écartées

Les trois sources prévues ont été essayées dans l'ordre imposé.

### a. geoBoundaries — **écartée**

L'API `https://www.geoboundaries.org/api/current/gbOpen/MDG/ADM{1,2,3}/`
répond (HTTP 200) et les GeoJSON se téléchargent (2,9 / 28,8 / 65,3 Mo). Les
comptages correspondent (22 / 119 / 1 579). Écartée pour deux raisons
techniques, pas de licence :

1. **Aucune hiérarchie.** Les Features ne portent que
   `shapeName, shapeISO, shapeID, shapeGroup, shapeType` ; `shapeISO` est vide et
   aucun code de parent n'est fourni. Les `code_parent` / `nom_parent` du contrat
   d'interface auraient dû être reconstitués par jointure spatiale, donc par
   approximation, alors que la source retenue les fournit explicitement.
2. **Millésimes incohérents entre niveaux.** L'ADM1 de geoBoundaries vient
   d'OpenStreetMap / Wambacher (2017, ODbL 1.0) tandis que ses ADM2 et ADM3
   sont… ce même COD-AB BNGRC/OCHA (2020, CC BY 3.0 IGO). Les communes ne
   s'emboîtent donc pas nécessairement dans les régions, et le fichier aurait
   mélangé deux licences.

Autrement dit, geoBoundaries redistribue déjà la source retenue pour les niveaux
2 et 3 : passer par HDX, c'est remonter à l'amont **avec** les pcodes intacts et
une licence unique pour les trois niveaux.

### b. HDX / OCHA — **retenue** (voir ci-dessus)

### c. GADM — **non sollicitée**

Inutile de la tester, la source (b) fonctionnant. Elle aurait de toute façon été
un dernier recours : la licence GADM interdit l'usage commercial et la
redistribution sans autorisation, ce qui est incompatible avec un dépôt public.

---

## Traitements appliqués

Le détail est dans `tools/fetch_boundaries.py` ; en résumé :

1. **CRS** — vérifié, et reprojeté en EPSG:4326 si la source changeait un jour.
   La source est déjà en WGS 84 : aucune reprojection n'a lieu aujourd'hui.
2. **Simplification** — `shapely.coverage_simplify(tolerance, simplify_boundary=True)`
   plutôt qu'un `simplify()` polygone par polygone : les arêtes *mitoyennes*
   sont simplifiées à l'identique de part et d'autre, donc les zones voisines
   restent jointives (un `simplify()` indépendant aurait ouvert un liseré de
   fond de carte entre chaque commune).

   | Niveau | Tolérance | ≈ au sol | Sommets source → produits |
   | --- | --- | --- | --- |
   | Région | 0,003° | 330 m | 444 810 → 23 393 |
   | District | 0,003° | 330 m | 648 839 → 42 653 |
   | Commune | 0,008° | 880 m | 1 468 386 → 54 046 |

   La tolérance ADM3 est dictée par la cible de **1,5 Mo** : avec 1 579 communes
   et des coordonnées à 5 décimales (~21 octets par couple), le budget est
   d'environ 35 sommets par commune. Le script échoue explicitement si le
   fichier repasse au-dessus de 1,5 Mo.
3. **Arrondi** — `shapely.set_precision(1e-5)` avant sérialisation, donc les
   contrôles de validité portent sur les coordonnées réellement écrites, et non
   sur des géométries que l'arrondi dégraderait ensuite. Écriture JSON compacte
   (`separators=(",", ":")`), sans membre `id`.
4. **Validité** — `is_valid` contrôlé après simplification ; réparation par
   `make_valid()` si besoin. En pratique : **0 géométrie invalide, 0 géométrie
   vide** aux trois niveaux, aucune réparation nécessaire.
5. **Noms** — espaces multiples réduits, préfixe technique retiré
   (`Cu Morombe` → `Morombe`), initiale de chaque mot en capitale sans écraser
   ce qui l'est déjà, ce qui préserve `Antsirabe I`, `Toamasina II`,
   `1er Arrondissement`, `Port-Berge (Boriziny-Vaovao)`, `Berevo/Ranobe` et les
   apostrophes malgaches (`Anosibe An'ala`).

   Une seule correction nominative explicite, dans `CORRECTIONS` : la source
   écrit `Amoron I Mania` là où le reste du jeu conserve bien les apostrophes
   (`Ambodirian'i Sahafary`) ; le nom est rétabli en **`Amoron'i Mania`**. Cette
   correction se propage aussi aux `nom_parent` des districts, la même fonction
   de nettoyage étant appliquée à tous les champs de nom.

---

## Réserves à connaître

- **22 régions, pas 23.** Le millésime 2018 précède le découpage de 2021, qui a
  scindé Vatovavy Fitovinany en Vatovavy et Fitovinany. Le COD-AB n'a pas été
  mis à jour ; c'est la référence humanitaire courante pour Madagascar. Aucune
  source ouverte, redistribuable et cohérente sur les trois niveaux ne propose
  le découpage à 23 régions à ce jour.
- **Noms de communes non uniques.** 150 communes portent un nom déjà utilisé
  ailleurs (`Morafeno` apparaît 7 fois). Seul `code_zone` identifie une zone.
  Pour un sélecteur ou une infobulle, désambiguïser avec `nom_parent`
  (« Morafeno — Vohipeno »).
- **Pavage ADM3 : 19 communes non jointives, défaut d'origine.** La source
  contient 19 zones dont une arête mitoyenne ne coïncide pas exactement avec sa
  voisine (autour d'Ivato, Tsiroanomandidy et Manakara Atsimo), soit ~212 km
  d'arêtes non nodées. Le recouvrement d'aire est nul (somme des aires = aire de
  l'union au km² près) : ce sont des sommets non partagés, pas des doublons de
  surface. Le script compte ces défauts **avant et après** simplification et
  n'alerte que s'il en ajoute — il n'en ajoute aucun. Non corrigé : réparer
  reviendrait à déplacer des limites officielles pour un artefact invisible à
  l'écran.
- **Communes urbaines grossières.** À 0,008°, les petites communes de
  l'agglomération d'Antananarivo (`Ambohidrapeto`, `Itaosy`, `Ivato Firaisana`,
  `Tanambao V`…, 2 à 6 km²) perdent jusqu'à ~43 % de leur aire. L'écart d'aire
  cumulé national reste de 0,009 %. Si un zoom fin sur Antananarivo devenait
  nécessaire, il faudra un fichier dédié à l'agglomération plutôt qu'abaisser la
  tolérance nationale, qui ferait exploser le budget de 1,5 Mo.
- **Le niveau ADM4 (17 465 fokontany) n'est pas extrait** : hors périmètre, et
  irréconciliable avec la cible de poids.

---

## Rafraîchir les données

```sh
# reconstruction complète (archive retéléchargée puis les 4 fichiers réécrits)
.venv/bin/python tools/fetch_boundaries.py --force --redownload

# reconstruction depuis l'archive déjà en cache (~10 s, sans réseau)
.venv/bin/python tools/fetch_boundaries.py --force

# sans option : ne fait rien si les 4 fichiers sont déjà là
.venv/bin/python tools/fetch_boundaries.py
```

Le script est **idempotent** : deux exécutions successives produisent des
fichiers identiques bit à bit. Il affiche à chaque niveau le nombre de zones, la
taille, le nombre de sommets, le CRS, les géométries invalides ou vides, l'état
du pavage, l'écart d'aire et les `code_parent` orphelins ; il sort en code 1 si
un seul de ces contrôles échoue, et n'écrit rien si le téléchargement échoue
(3 tentatives, backoff 5 / 15 / 45 s, délai socket de 60 s).

L'archive de 66,3 Mo est mise en cache **hors du dépôt**, dans
`$TMPDIR/mdg_cod_ab/` (`--cache-dir` pour en changer), afin qu'elle ne puisse
pas être commitée par inadvertance. Elle est écrite en `.part` puis renommée :
une coupure réseau ne laisse jamais d'archive tronquée qu'une exécution
ultérieure prendrait pour valide.

---

## Contrat d'interface (rappel)

Chaque `Feature` des trois GeoJSON porte exactement ces cinq propriétés :

| Propriété | Type | Détail |
| --- | --- | --- |
| `code_zone` | str non vide | pcode BNGRC, unique dans le fichier (ex. `MG11`, `MG11101001A`, `MG11101001`) |
| `nom_zone` | str | nom d'affichage nettoyé |
| `niveau` | str | `"Région"`, `"District"` ou `"Commune"` selon le fichier |
| `code_parent` | str \| null | `code_zone` du parent ; `null` en ADM1 |
| `nom_parent` | str \| null | `nom_zone` du parent ; `null` en ADM1 |

`zones.csv` reprend les 1 720 zones des trois niveaux, colonnes
`code_zone,nom_affiche,niveau,code_parent,nom_parent` (`nom_affiche` = `nom_zone`
du GeoJSON ; `code_parent` et `nom_parent` sont vides pour les régions).

Vérifié sur les fichiers produits : jeux de propriétés conformes aux trois
niveaux, `code_zone` unique partout, **0 orphelin** District → Région et
Commune → District, `nom_parent` cohérent avec le `nom_zone` du parent dans
100 % des cas, aucune coordonnée au-delà de 5 décimales, CRS relu par geopandas
à `EPSG:4326` pour les trois fichiers.
