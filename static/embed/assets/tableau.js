/* Iframe « établissements partenaires eAriary » — tableau.
 *
 * Même registre que la page carte, sans la carte : une liste triable, filtrée
 * par région et par type de marchand, chaque ligne renvoyant à Google Maps.
 * Les données et leur nettoyage viennent de `data.js`, les couleurs de
 * `categories.js` ; le paramétrage passe par la chaîne de requête de l'iframe
 * (voir README), l'application hôte n'ayant ni script à charger ni état à gérer.
 */

(function (global) {
  "use strict";

  var doc = global.document;

  /* Une ligne relue en direct dont la ville est inconnue de la table
     ville → région de l'instantané reste dans le tableau, sous ce libellé,
     plutôt que d'en disparaître. */
  var REGION_VIDE = "Région à préciser";

  function styleDe(categorie) {
    return global.EARIARY_CATEGORIES.styleDe(categorie);
  }

  /* ------------------------------ Paramètres ----------------------------- */

  var params = new URLSearchParams(global.location.search);

  function param(nom, defaut) {
    var valeur = params.get(nom);
    return valeur === null || valeur === "" ? defaut : valeur;
  }

  var TRIS = ["nom", "categorie", "region", "province"];

  var options = {
    entete: param("header", "1") !== "0",
    // Clair par défaut : la page est un document public, elle doit avoir la
    // même apparence pour tout le monde plutôt que de suivre le réglage
    // système du visiteur. `?theme=auto` rétablit ce suivi.
    theme: ["auto", "clair", "sombre"].indexOf(param("theme", "clair")) !== -1
      ? param("theme", "clair")
      : "clair",
    direct: param("live", "1") !== "0",
    titre: param("titre", ""),
    recherche: param("q", ""),
    // Une seule valeur par filtre : le tableau se lit comme un registre, deux
    // listes déroulantes y sont plus lisibles qu'une rangée de puces. Une
    // liste séparée par des virgules — le format de la page carte — est
    // acceptée, seule la première valeur est retenue.
    region: param("region", "").split(",")[0].trim(),
    categorie: param("categorie", "").split(",")[0].trim(),
    ville: param("ville", "").split(",")[0].trim(),
    tri: TRIS.indexOf(param("tri", "region")) !== -1 ? param("tri", "region") : "region",
    sens: param("sens", "asc") === "desc" ? "desc" : "asc",
    origine: param("origin", "*"),
  };

  /* --------------------------------- État -------------------------------- */

  var etat = {
    tous: [],
    visibles: [],
    selection: null, // index dans `tous`
    // Instantané ou Sheet relu : plus affiché dans la page — le tableau n'a
    // pas de note de provenance — mais toujours transmis à l'application hôte
    // dans le message « pret », qui peut en faire ce qu'elle veut.
    source: "instantane",
    tri: options.tri,
    sens: options.sens,
  };

  var el = {
    app: doc.getElementById("app"),
    titre: doc.getElementById("titre"),
    recherche: doc.getElementById("recherche"),
    region: doc.getElementById("region"),
    categorie: doc.getElementById("categorie"),
    compte: doc.getElementById("compte"),
    reset: doc.getElementById("reset"),
    lignes: doc.getElementById("lignes"),
    vide: doc.getElementById("vide"),
    entetes: doc.querySelectorAll("th[data-tri]"),
  };

  /* ------------------------------- Utilitaires --------------------------- */

  function echapper(texte) {
    return String(texte).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var collateur = new Intl.Collator("fr", { sensitivity: "base", numeric: true });

  /* Comparaison de recherche insensible aux accents : « hotel » trouve
     « Hôtel », comme le fait sort_fr côté Streamlit pour le tri. */
  function pliage(texte) {
    return String(texte)
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  }

  function annoncer(type, charge) {
    if (global.parent === global) return;
    // Les clés de l'enveloppe sont posées en dernier : c'est sur `source` que
    // l'hôte reconnaît l'iframe, et une charge utile ne doit pas pouvoir
    // l'écraser — d'où aussi `provenance` plutôt que `source` dans « pret ».
    var message = {};
    Object.keys(charge || {}).forEach(function (cle) {
      message[cle] = charge[cle];
    });
    message.source = "eariary-embed";
    message.type = type;
    try {
      global.parent.postMessage(message, options.origine);
    } catch (e) {
      /* origine refusée par l'hôte : l'iframe reste fonctionnelle sans. */
    }
  }

  /* -------------------------------- Lignes -------------------------------- */

  /* Le lien pointe sur les coordonnées, pas sur le nom : deux commerces
     peuvent porter la même enseigne, et une recherche par nom tomberait à côté.
     Sans coordonnée exploitable, la fiche reste dans le tableau — c'est la
     règle de la page carte — et le dit, avec la valeur brute du Sheet en
     infobulle. */
  function localisation(etablissement) {
    if (etablissement.lat === null || etablissement.lon === null) {
      var brut = etablissement.coordonnees_brutes;
      return (
        '<span class="warn"' +
        (brut ? ' title="' + echapper(brut) + '"' : "") +
        ">Non localisé</span>"
      );
    }
    return (
      '<a class="gmaps" target="_blank" rel="noopener" href="https://www.google.com/maps?q=' +
      etablissement.lat +
      "," +
      etablissement.lon +
      '" aria-label="Ouvrir ' +
      echapper(etablissement.nom) +
      ' dans Google Maps">Google Maps' +
      '<svg viewBox="0 0 24 24" aria-hidden="true">' +
      '<path d="M14 3v2h3.6l-9.8 9.8 1.4 1.4L19 6.4V10h2V3h-7Z"/>' +
      '<path d="M5 5h5V3H3v18h18v-7h-2v5H5V5Z"/></svg></a>'
    );
  }

  function ligne(etablissement) {
    var style = styleDe(etablissement.categorie);
    var tr = doc.createElement("tr");
    tr.dataset.id = String(etablissement.id);
    tr.setAttribute("aria-current", etablissement.id === etat.selection ? "true" : "false");

    // `data-label` sert de titre de champ quand le tableau se replie en blocs,
    // sous 680 px : les en-têtes de colonne disparaissent alors.
    tr.innerHTML =
      '<td class="c-nom" data-label="Établissement">' +
      '<button type="button" class="nom">' +
      echapper(etablissement.nom) +
      "</button></td>" +
      '<td class="c-type" data-label="Type">' +
      '<span class="swatch" style="background:' +
      style.couleur +
      '"></span>' +
      echapper(etablissement.categorie) +
      "</td>" +
      '<td class="c-region" data-label="Région">' +
      echapper(etablissement.region || REGION_VIDE) +
      "</td>" +
      '<td class="c-ville" data-label="Ville">' +
      echapper(etablissement.province) +
      "</td>" +
      '<td class="c-lien" data-label="Localisation">' +
      localisation(etablissement) +
      "</td>";

    tr.querySelector(".nom").addEventListener("click", function () {
      selectionner(etablissement.id);
    });
    return tr;
  }

  function dessinerLignes() {
    el.lignes.textContent = "";
    el.vide.hidden = etat.visibles.length > 0;

    var fragment = doc.createDocumentFragment();
    etat.visibles.forEach(function (etablissement) {
      fragment.appendChild(ligne(etablissement));
    });
    el.lignes.appendChild(fragment);
  }

  /* --------------------------------- Tri ---------------------------------- */

  function valeurDeTri(etablissement, cle) {
    if (cle === "region") return etablissement.region || REGION_VIDE;
    return etablissement[cle] || "";
  }

  function trier(etablissements) {
    var sens = etat.sens === "desc" ? -1 : 1;
    return etablissements.slice().sort(function (a, b) {
      var ecart = collateur.compare(valeurDeTri(a, etat.tri), valeurDeTri(b, etat.tri));
      // À valeur égale — toute une région, tout un type — le nom départage :
      // sans quoi l'ordre des lignes changerait d'un rendu à l'autre.
      if (ecart === 0 && etat.tri !== "nom") return collateur.compare(a.nom, b.nom);
      return ecart * sens;
    });
  }

  function majEntetes() {
    Array.prototype.slice.call(el.entetes).forEach(function (th) {
      var actif = th.dataset.tri === etat.tri;
      th.setAttribute(
        "aria-sort",
        actif ? (etat.sens === "desc" ? "descending" : "ascending") : "none"
      );
    });
  }

  function basculerTri(cle) {
    if (etat.tri === cle) {
      etat.sens = etat.sens === "asc" ? "desc" : "asc";
    } else {
      etat.tri = cle;
      etat.sens = "asc";
    }
    majEntetes();
    appliquer();
  }

  /* -------------------------------- Filtres ------------------------------- */

  /* Les deux listes déroulantes portent l'effectif de chaque valeur : elles
     servent de filtre et de répartition, comme les puces de la page carte. */
  function remplir(select, comptes, libelleTout, choisie) {
    select.textContent = "";
    var tout = doc.createElement("option");
    tout.value = "";
    tout.textContent = libelleTout;
    select.appendChild(tout);

    var valeurs = Object.keys(comptes).sort(collateur.compare);
    valeurs.forEach(function (valeur) {
      var option = doc.createElement("option");
      option.value = valeur;
      option.textContent = valeur + " (" + comptes[valeur] + ")";
      select.appendChild(option);
    });
    select.value = valeurs.indexOf(choisie) !== -1 ? choisie : "";
  }

  function comptesPar(cle) {
    return etat.tous.reduce(function (acc, etablissement) {
      var valeur = valeurDeTri(etablissement, cle);
      acc[valeur] = (acc[valeur] || 0) + 1;
      return acc;
    }, {});
  }

  function dessinerFiltres() {
    remplir(
      el.region,
      comptesPar("region"),
      "Toutes les régions",
      el.region.value || options.region
    );
    remplir(
      el.categorie,
      comptesPar("categorie"),
      "Tous les types",
      el.categorie.value || options.categorie
    );
  }

  function appliquer() {
    var recherche = pliage(el.recherche.value.trim());
    var region = el.region.value;
    var categorie = el.categorie.value;

    // Une sélection vide vaut « tout afficher » — même règle que l'app.
    var retenus = etat.tous.filter(function (e) {
      if (region && (e.region || REGION_VIDE) !== region) return false;
      if (categorie && e.categorie !== categorie) return false;
      if (options.ville && e.province !== options.ville) return false;
      if (
        recherche &&
        pliage(e.nom).indexOf(recherche) === -1 &&
        pliage(e.province).indexOf(recherche) === -1 &&
        pliage(e.region).indexOf(recherche) === -1 &&
        pliage(e.categorie).indexOf(recherche) === -1
      ) {
        return false;
      }
      return true;
    });

    etat.visibles = trier(retenus);

    var sansPoint = etat.visibles.filter(function (e) {
      return e.lat === null;
    }).length;
    el.compte.textContent =
      etat.visibles.length +
      (etat.visibles.length > 1 ? " établissements" : " établissement") +
      (sansPoint ? " — " + sansPoint + " non localisé" + (sansPoint > 1 ? "s" : "") : "");

    el.reset.hidden = !(recherche || region || categorie);

    if (
      etat.selection !== null &&
      !etat.visibles.some(function (e) {
        return e.id === etat.selection;
      })
    ) {
      etat.selection = null;
    }

    dessinerLignes();
    annoncer("filtre", {
      visibles: etat.visibles.length,
      recherche: el.recherche.value.trim(),
      region: region,
      categorie: categorie,
      tri: etat.tri,
      sens: etat.sens,
    });
  }

  /* ------------------------------ Sélection ------------------------------- */

  /* Cliquer un nom ne quitte pas la page : cela signale la fiche à
     l'application hôte — qui peut y centrer sa propre carte — et la souligne
     dans le tableau. Le lien Google Maps, lui, ouvre un nouvel onglet. */
  function selectionner(id) {
    etat.selection = id;
    var etablissement = etat.tous[id];

    Array.prototype.slice.call(el.lignes.querySelectorAll("tr")).forEach(function (tr) {
      tr.setAttribute("aria-current", tr.dataset.id === String(id) ? "true" : "false");
    });

    annoncer("selection", {
      etablissement: {
        nom: etablissement.nom,
        categorie: etablissement.categorie,
        region: etablissement.region,
        province: etablissement.province,
        lat: etablissement.lat,
        lon: etablissement.lon,
      },
    });
  }

  /* ------------------------------ Démarrage ------------------------------- */

  function indexer(etablissements) {
    return etablissements.map(function (e, index) {
      return {
        id: index,
        nom: e.nom,
        categorie: e.categorie,
        province: e.province,
        // L'instantané la calcule par appartenance au polygone ADM1 ; une
        // ligne relue en direct la tient de la table ville → région.
        region: e.region || global.EARIARY_DATA.regionDe(e.province),
        lat: typeof e.lat === "number" ? e.lat : null,
        lon: typeof e.lon === "number" ? e.lon : null,
        coordonnees_brutes: e.coordonnees_brutes || "",
      };
    });
  }

  function charger(donnees) {
    etat.tous = indexer(donnees.etablissements);
    etat.source = donnees.source;
    etat.selection = null;
    dessinerFiltres();
    appliquer();
  }

  function demarrer() {
    if (options.theme !== "auto") {
      doc.documentElement.dataset.theme = options.theme;
    }
    el.app.dataset.header = options.entete ? "1" : "0";
    if (options.titre) el.titre.textContent = options.titre;
    el.recherche.value = options.recherche;
    majEntetes();

    el.recherche.addEventListener("input", appliquer);
    el.region.addEventListener("change", appliquer);
    el.categorie.addEventListener("change", appliquer);
    el.reset.addEventListener("click", function () {
      el.recherche.value = "";
      el.region.value = "";
      el.categorie.value = "";
      appliquer();
      el.recherche.focus();
    });
    Array.prototype.slice.call(el.entetes).forEach(function (th) {
      th.querySelector("button").addEventListener("click", function () {
        basculerTri(th.dataset.tri);
      });
    });

    var snap = global.EARIARY_DATA.instantane();
    if (snap) charger(snap);

    var termine = function () {
      annoncer("pret", {
        total: etat.tous.length,
        visibles: etat.visibles.length,
        provenance: etat.source,
      });
    };

    if (!options.direct) {
      if (!snap) el.vide.textContent = "Aucune donnée embarquée.";
      termine();
      return;
    }

    global.EARIARY_DATA.enDirect()
      .then(function (donnees) {
        charger(donnees);
      })
      .catch(function () {
        // Silencieux : l'instantané reste affiché. L'hôte, lui, apprend par le
        // champ `provenance` du message « pret » que c'est une copie.
        if (!snap) {
          el.vide.textContent =
            "Données indisponibles — la source n'a pas répondu et aucune copie n'est embarquée.";
          el.vide.hidden = false;
        }
      })
      .then(termine);
  }

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", demarrer);
  } else {
    demarrer();
  }
})(window);
