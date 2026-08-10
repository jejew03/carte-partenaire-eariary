/* Registre des partenaires eAriary — page tableau.
 *
 * Même registre que la page carte, sans la carte : une liste triable, filtrée
 * par région et par type de marchand, chaque ligne renvoyant à Google Maps.
 * Les données et leur nettoyage viennent de `donnees.js`, les couleurs de
 * `categories.js` ; le paramétrage passe par la chaîne de requête de l'iframe
 * (voir README), l'application hôte n'ayant ni script à charger ni état à gérer.
 *
 * Le Sheet est relu périodiquement : une ligne ajoutée apparaît d'elle-même,
 * sans que le tri, les filtres, la recherche ou la position de défilement du
 * visiteur ne soient perdus.
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

  /* ------------------------------ Paramètres ------------------------------ */

  var params = new URLSearchParams(global.location.search);

  function param(nom, defaut) {
    var valeur = params.get(nom);
    return valeur === null || valeur === "" ? defaut : valeur;
  }

  /* Période de relecture du Sheet, en secondes. Plancher à 60 s : au-delà de
     ce rythme on interrogerait Google plus souvent que le Sheet ne change.
     `0` fige la page sur ce qu'elle a chargé au démarrage. */
  function periode() {
    var secondes = Number(param("refresh", "300"));
    if (!isFinite(secondes) || secondes <= 0) return 0;
    return Math.max(secondes, 60) * 1000;
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
    periode: periode(),
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

  /* --------------------------------- État --------------------------------- */

  var etat = {
    tous: [],
    visibles: [],
    // Index dans `tous` pour le DOM, et clé stable pour retrouver la même
    // fiche après un rafraîchissement — l'index, lui, bouge dès qu'une ligne
    // est insérée dans le Sheet.
    selection: null,
    selectionCle: null,
    // Instantané ou Sheet relu : le tableau ne porte pas de note de provenance
    // — c'est un registre posé dans l'application hôte, à qui il revient de
    // dire d'où viennent ses données — mais l'information lui est transmise
    // dans le message « pret ».
    source: "instantane",
    // Colonnes facultatives réellement remplies dans le Sheet.
    champs: [],
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
    thContact: doc.getElementById("th-contact"),
    entetes: doc.querySelectorAll("th[data-tri]"),
  };

  /* ------------------------------ Utilitaires ----------------------------- */

  function echapper(texte) {
    return String(texte).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var collateur = new Intl.Collator("fr", { sensitivity: "base", numeric: true });

  /* Recherche insensible aux accents : « hotel » trouve « Hôtel ». */
  var pliage = global.EARIARY_DONNEES.plier;

  function annoncer(type, charge) {
    if (global.parent === global) return;
    // Les clés de l'enveloppe sont posées en dernier : c'est sur `source` que
    // l'hôte reconnaît l'iframe, et une charge utile ne doit pas pouvoir
    // l'écraser — d'où aussi `provenance` plutôt que `source` dans « pret ».
    var message = {};
    Object.keys(charge || {}).forEach(function (cle) {
      message[cle] = charge[cle];
    });
    message.source = "eariary-partenaires";
    message.type = type;
    try {
      global.parent.postMessage(message, options.origine);
    } catch (e) {
      /* origine refusée par l'hôte : la page reste fonctionnelle sans. */
    }
  }

  /* --------------------------- Champs facultatifs -------------------------- */

  function telHref(valeur) {
    // Un `tel:` ne supporte ni espaces ni parenthèses ; le libellé affiché,
    // lui, garde la mise en forme saisie dans le Sheet.
    return "tel:" + String(valeur).replace(/[^\d+]/g, "");
  }

  function siteHref(valeur) {
    var texte = String(valeur).trim();
    if (/^https?:\/\//i.test(texte)) return texte;
    // Sans protocole, le lien serait relatif à l'iframe. On préfixe en https
    // plutôt que de recopier la cellule : une valeur exotique — « javascript: »
    // et consorts — devient alors un nom d'hôte inoffensif plutôt qu'un schéma.
    return "https://" + texte.replace(/^\/+/, "");
  }

  function libelleSite(valeur) {
    var texte = String(valeur).trim().replace(/^https?:\/\//i, "").replace(/\/$/, "");
    return texte.length > 28 ? texte.slice(0, 27) + "…" : texte;
  }

  var ICONE_EXTERNE =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M14 3v2h3.6l-9.8 9.8 1.4 1.4L19 6.4V10h2V3h-7Z"/>' +
    '<path d="M5 5h5V3H3v18h18v-7h-2v5H5V5Z"/></svg>';

  function aChamp(cle) {
    return etat.champs.indexOf(cle) !== -1;
  }

  /* La colonne « Contact » n'existe que si le Sheet porte au moins un numéro
     ou un site. Tant que ce n'est pas le cas, le tableau garde exactement les
     cinq colonnes qu'il a toujours eues. */
  function afficheContact() {
    return aChamp("telephone") || aChamp("site");
  }

  /* -------------------------------- Lignes --------------------------------- */

  /* Le lien pointe sur les coordonnées, pas sur le nom : deux commerces peuvent
     porter la même enseigne, et une recherche par nom tomberait à côté. Sans
     coordonnée exploitable, la fiche reste dans le tableau — c'est la règle de
     la page carte — et le dit, avec la valeur brute du Sheet en infobulle. */
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
      '<a class="lien" target="_blank" rel="noopener" href="https://www.google.com/maps?q=' +
      etablissement.lat +
      "," +
      etablissement.lon +
      '" aria-label="Ouvrir ' +
      echapper(etablissement.nom) +
      ' dans Google Maps">Google Maps' +
      ICONE_EXTERNE +
      "</a>"
    );
  }

  function contact(etablissement) {
    var blocs = [];
    if (etablissement.telephone) {
      blocs.push(
        '<a class="tel" href="' +
          echapper(telHref(etablissement.telephone)) +
          '">' +
          echapper(etablissement.telephone) +
          "</a>"
      );
    }
    if (etablissement.site) {
      blocs.push(
        '<a class="lien" target="_blank" rel="noopener" href="' +
          echapper(siteHref(etablissement.site)) +
          '">' +
          echapper(libelleSite(etablissement.site)) +
          ICONE_EXTERNE +
          "</a>"
      );
    }
    if (!blocs.length) return '<span class="warn">—</span>';
    return '<span class="infos">' + blocs.join("") + "</span>";
  }

  /* Adresse et horaires sous le nom : ce sont des précisions sur « où » et
     « quand », pas des colonnes. Leur donner une colonne chacune ferait un
     registre de huit colonnes, illisible dès le premier écran étroit. */
  function sousLigne(etablissement) {
    var bouts = [];
    if (etablissement.adresse) bouts.push(echapper(etablissement.adresse));
    if (etablissement.horaires) bouts.push(echapper(etablissement.horaires));
    if (!bouts.length) return "";
    return (
      '<div class="sous">' +
      bouts.join('<span class="sep" aria-hidden="true">·</span>') +
      "</div>"
    );
  }

  function ligne(etablissement) {
    var style = styleDe(etablissement.categorie);
    var tr = doc.createElement("tr");
    tr.dataset.id = String(etablissement.id);
    tr.setAttribute(
      "aria-current",
      etablissement.id === etat.selection ? "true" : "false"
    );

    // `data-label` sert de titre de champ quand le tableau se replie en blocs,
    // sous 680 px : les en-têtes de colonne disparaissent alors.
    tr.innerHTML =
      '<td class="c-nom" data-label="Établissement">' +
      '<button type="button" class="nom">' +
      echapper(etablissement.nom) +
      "</button>" +
      sousLigne(etablissement) +
      "</td>" +
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
      (afficheContact()
        ? '<td class="c-contact" data-label="Contact">' + contact(etablissement) + "</td>"
        : "") +
      '<td class="c-lien" data-label="Localisation">' +
      localisation(etablissement) +
      "</td>";

    tr.querySelector(".nom").addEventListener("click", function () {
      selectionner(etablissement.id);
    });
    return tr;
  }

  function dessinerLignes() {
    el.thContact.hidden = !afficheContact();
    el.lignes.textContent = "";
    el.vide.hidden = etat.visibles.length > 0;

    var fragment = doc.createDocumentFragment();
    etat.visibles.forEach(function (etablissement) {
      fragment.appendChild(ligne(etablissement));
    });
    el.lignes.appendChild(fragment);
  }

  /* ---------------------------------- Tri ---------------------------------- */

  function valeurDeTri(etablissement, cle) {
    if (cle === "region") return etablissement.region || REGION_VIDE;
    return etablissement[cle] || "";
  }

  function trier(etablissements) {
    var sens = etat.sens === "desc" ? -1 : 1;
    return etablissements.slice().sort(function (a, b) {
      var ecart = collateur.compare(valeurDeTri(a, etat.tri), valeurDeTri(b, etat.tri));
      // À valeur égale — toute une région, tout un type — le nom départage :
      // sans quoi l'ordre des lignes changerait d'un rendu à l'autre, et un
      // rafraîchissement rebattrait le tableau sous les yeux du visiteur.
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

  /* -------------------------------- Filtres -------------------------------- */

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

    // Une sélection vide vaut « tout afficher » — même règle que l'application
    // interne.
    var retenus = etat.tous.filter(function (e) {
      if (region && (e.region || REGION_VIDE) !== region) return false;
      if (categorie && e.categorie !== categorie) return false;
      if (options.ville && e.province !== options.ville) return false;
      if (
        recherche &&
        pliage(e.nom).indexOf(recherche) === -1 &&
        pliage(e.province).indexOf(recherche) === -1 &&
        pliage(e.region).indexOf(recherche) === -1 &&
        pliage(e.categorie).indexOf(recherche) === -1 &&
        pliage(e.adresse || "").indexOf(recherche) === -1
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
      etat.selectionCle = null;
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

  /* ------------------------------- Sélection ------------------------------- */

  /* Cliquer un nom ne quitte pas la page : cela signale la fiche à
     l'application hôte — qui peut y centrer sa propre carte — et la souligne
     dans le tableau. Le lien Google Maps, lui, ouvre un nouvel onglet. */
  function selectionner(id) {
    var etablissement = etat.tous[id];
    if (!etablissement) return;
    etat.selection = id;
    etat.selectionCle = etablissement.cle;

    Array.prototype.slice.call(el.lignes.querySelectorAll("tr")).forEach(function (tr) {
      tr.setAttribute("aria-current", tr.dataset.id === String(id) ? "true" : "false");
    });

    var fiche = {
      nom: etablissement.nom,
      categorie: etablissement.categorie,
      region: etablissement.region,
      province: etablissement.province,
      lat: etablissement.lat,
      lon: etablissement.lon,
    };
    ["adresse", "horaires", "telephone", "site"].forEach(function (cle) {
      if (etablissement[cle]) fiche[cle] = etablissement[cle];
    });
    annoncer("selection", { etablissement: fiche });
  }

  /* ------------------------------- Démarrage ------------------------------- */

  /* Clé stable d'une fiche : ce qui l'identifie indépendamment de sa position
     dans le Sheet. L'index, lui, se décale dès qu'une ligne est insérée. */
  function cleDe(e) {
    return [e.nom, e.province, e.lat, e.lon].join(" ");
  }

  function indexer(etablissements) {
    return etablissements.map(function (e, index) {
      var fiche = {
        id: index,
        nom: e.nom,
        categorie: e.categorie,
        province: e.province,
        // L'instantané la calcule par appartenance au polygone ADM1 ; une
        // ligne relue en direct la tient de la table ville → région.
        region: e.region || global.EARIARY_DONNEES.regionDe(e.province),
        lat: typeof e.lat === "number" ? e.lat : null,
        lon: typeof e.lon === "number" ? e.lon : null,
        coordonnees_brutes: e.coordonnees_brutes || "",
      };
      ["adresse", "horaires", "telephone", "site"].forEach(function (cle) {
        if (e[cle]) fiche[cle] = e[cle];
      });
      fiche.cle = cleDe(fiche);
      return fiche;
    });
  }

  function charger(donnees) {
    etat.tous = indexer(donnees.etablissements);
    etat.champs = donnees.champs || [];
    etat.source = donnees.source;

    // La fiche sélectionnée survit au rafraîchissement si elle est toujours
    // dans le Sheet ; elle disparaît proprement sinon.
    etat.selection = null;
    if (etat.selectionCle) {
      etat.tous.forEach(function (e) {
        if (e.cle === etat.selectionCle) etat.selection = e.id;
      });
      if (etat.selection === null) etat.selectionCle = null;
    }

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

    var snap = global.EARIARY_DONNEES.instantane();
    if (snap) charger(snap);

    var pret = false;
    function annoncerPret() {
      if (pret) return;
      pret = true;
      annoncer("pret", {
        total: etat.tous.length,
        visibles: etat.visibles.length,
        provenance: etat.source,
      });
    }

    if (!options.direct) {
      if (!snap) el.vide.textContent = "Aucune donnée embarquée.";
      annoncerPret();
      return;
    }

    var suivi = global.EARIARY_DONNEES.suivre({
      intervalle: options.periode,
      surDonnees: function (donnees, contexte) {
        charger(donnees);
        if (!contexte.premier) {
          annoncer("maj", {
            total: etat.tous.length,
            visibles: etat.visibles.length,
          });
        }
        annoncerPret();
      },
      surEchec: function (erreur, contexte) {
        // Silencieux : l'instantané reste affiché. L'hôte, lui, apprend par le
        // champ `provenance` du message « pret » que c'est une copie.
        if (contexte.premier && !snap) {
          el.vide.textContent =
            "Données indisponibles — la source n'a pas répondu et aucune copie n'est embarquée.";
          el.vide.hidden = false;
        }
        annoncerPret();
      },
    });

    // L'hôte peut demander une relecture immédiate, par exemple après avoir
    // lui-même écrit dans le Sheet.
    global.addEventListener("message", function (evenement) {
      var donnees = evenement.data;
      if (!donnees || donnees.source !== "eariary-hote") return;
      if (donnees.type === "rafraichir") suivi.relire();
    });
  }

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", demarrer);
  } else {
    demarrer();
  }
})(window);
