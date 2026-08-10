/* Page tableau : le même registre que la page carte, sans la carte.
 *
 * Dépendances chargées avant ce fichier (voir tableau.html) :
 *   assets/instantane.js   window.EARIARY_PARTENAIRES
 *   assets/categories.js   window.EARIARY_CATEGORIES
 *   assets/donnees.js      window.EARIARY_DONNEES
 *
 * Le paramétrage se fait par la chaîne de requête de l'iframe (voir README) :
 * l'application hôte n'a aucun script à charger ni état à gérer.
 *
 * Écrit en ES5 (var, pas de classes) : ces pages sont intégrées dans des
 * applications tierces dont on ne maîtrise pas le parc de navigateurs.
 */

(function (global) {
  "use strict";

  var doc = global.document;

  // Libellé des fiches sans région : une ville ajoutée au Sheet depuis la
  // dernière génération de l'instantané n'est pas encore dans la table
  // ville -> région. La ligne reste dans le tableau sous ce libellé.
  var REGION_VIDE = "Région à préciser";

  // Colonnes triables, par ordre d'apparition dans le tableau.
  var TRIS = ["nom", "categorie", "region", "province"];

  // Champs facultatifs du Sheet, présents dans une fiche seulement s'ils sont
  // renseignés.
  var CHAMPS_FACULTATIFS = ["adresse", "horaires", "telephone", "site"];

  /* ------------------------------ Paramètres ------------------------------ */

  var params = new URLSearchParams(global.location.search);

  /** Valeur d'un paramètre d'URL, ou `defaut` s'il est absent ou vide. */
  function param(nom, defaut) {
    var valeur = params.get(nom);
    return valeur === null || valeur === "" ? defaut : valeur;
  }

  /** Valeur si elle fait partie des valeurs admises, sinon la première. */
  function parmi(nom, admises) {
    var valeur = param(nom, admises[0]);
    return admises.indexOf(valeur) !== -1 ? valeur : admises[0];
  }

  /**
   * Filtre à valeur unique. Une liste séparée par des virgules — le format de
   * la page carte — est acceptée : seule la première valeur est retenue.
   */
  function valeurUnique(nom) {
    return param(nom, "").split(",")[0].trim();
  }

  /**
   * Période de relecture du Sheet, en millisecondes.
   * Plancher à 60 s pour ne pas interroger Google plus vite que le Sheet ne
   * change ; `refresh=0` désactive la relecture périodique.
   */
  function periode() {
    var secondes = Number(param("refresh", "300"));
    if (!isFinite(secondes) || secondes <= 0) return 0;
    return Math.max(secondes, 60) * 1000;
  }

  var options = {
    entete: param("header", "1") !== "0",
    // Thème clair par défaut : la page est un document public, son apparence
    // ne doit pas dépendre du réglage système du visiteur. `theme=auto` le
    // rétablit.
    theme: parmi("theme", ["clair", "sombre", "auto"]),
    direct: param("live", "1") !== "0",
    periode: periode(),
    titre: param("titre", ""),
    recherche: param("q", ""),
    region: valeurUnique("region"),
    categorie: valeurUnique("categorie"),
    // Cadrage posé par l'hôte : aucune commande dans l'interface, le visiteur
    // ne peut pas le défaire.
    ville: valeurUnique("ville"),
    tri: parmi("tri", ["region", "nom", "categorie", "province"]),
    sens: param("sens", "asc") === "desc" ? "desc" : "asc",
    origine: param("origin", "*"),
  };

  /* --------------------------------- État --------------------------------- */

  var etat = {
    tous: [], // toutes les fiches
    visibles: [], // fiches retenues par les filtres, déjà triées
    selection: null, // index dans `tous`, ou null
    selectionCle: null, // clé stable de la fiche sélectionnée (voir cleDe)
    source: "instantane", // "instantane" ou "direct", transmis à l'hôte
    champs: [], // champs facultatifs remplis dans le Sheet
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

  /** Couleur et glyphe d'une catégorie (assets/categories.js). */
  function styleDe(categorie) {
    return global.EARIARY_CATEGORIES.styleDe(categorie);
  }

  /** Échappement HTML. À appliquer à toute valeur venant du Sheet. */
  function echapper(texte) {
    return String(texte).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var collateur = new Intl.Collator("fr", { sensitivity: "base", numeric: true });

  /** Minuscules sans accents : « hotel » doit trouver « Hôtel ». */
  var pliage = global.EARIARY_DONNEES.plier;

  /**
   * Envoie un message à l'application hôte.
   * `source` et `type` sont posés en dernier : c'est sur eux que l'hôte
   * reconnaît l'iframe, une charge utile ne doit pas pouvoir les écraser.
   */
  function annoncer(type, charge) {
    if (global.parent === global) return;
    var message = {};
    Object.keys(charge || {}).forEach(function (cle) {
      message[cle] = charge[cle];
    });
    message.source = "eariary-partenaires";
    message.type = type;
    try {
      global.parent.postMessage(message, options.origine);
    } catch (e) {
      // Origine refusée par l'hôte : la page reste utilisable sans messages.
    }
  }

  /* --------------------------- Champs facultatifs -------------------------- */

  /** Lien téléphonique : `tel:` n'accepte ni espaces ni parenthèses. */
  function telHref(valeur) {
    return "tel:" + String(valeur).replace(/[^\d+]/g, "");
  }

  /**
   * URL d'un site.
   * Sans protocole, le lien serait relatif à l'iframe : on préfixe en https.
   * Ce préfixe neutralise aussi une valeur du type « javascript:… », qui
   * devient un nom d'hôte inoffensif.
   */
  function siteHref(valeur) {
    var texte = String(valeur).trim();
    if (/^https?:\/\//i.test(texte)) return texte;
    return "https://" + texte.replace(/^\/+/, "");
  }

  /** Libellé d'un site : sans protocole, tronqué. */
  function libelleSite(valeur) {
    var texte = String(valeur).trim().replace(/^https?:\/\//i, "").replace(/\/$/, "");
    return texte.length > 28 ? texte.slice(0, 27) + "…" : texte;
  }

  var ICONE_EXTERNE =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M14 3v2h3.6l-9.8 9.8 1.4 1.4L19 6.4V10h2V3h-7Z"/>' +
    '<path d="M5 5h5V3H3v18h18v-7h-2v5H5V5Z"/></svg>';

  /**
   * La colonne « Contact » n'est affichée que si le Sheet porte au moins un
   * téléphone ou un site : une colonne vide laisserait croire qu'on ne sait
   * pas joindre les partenaires.
   */
  function afficheContact() {
    return etat.champs.indexOf("telephone") !== -1 || etat.champs.indexOf("site") !== -1;
  }

  /* -------------------------------- Lignes --------------------------------- */

  /**
   * Cellule « Localisation ».
   * Le lien pointe sur les coordonnées et non sur le nom : deux commerces
   * peuvent porter la même enseigne.
   */
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

  /** Cellule « Contact » : téléphone puis site, l'un sous l'autre. */
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

  /**
   * Adresse et horaires, affichés sous le nom.
   * Ils ne sont pas des colonnes : à six colonnes, le tableau déborderait dès
   * le premier écran étroit.
   */
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

  /**
   * Une ligne du tableau.
   * `data-label` sert d'étiquette de champ quand le tableau se replie en blocs
   * sous 680 px, les en-têtes de colonne étant alors masqués.
   */
  function ligne(etablissement) {
    var style = styleDe(etablissement.categorie);
    var tr = doc.createElement("tr");
    tr.dataset.id = String(etablissement.id);
    tr.setAttribute(
      "aria-current",
      etablissement.id === etat.selection ? "true" : "false"
    );

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

  /** Redessine le corps du tableau. */
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

  /** Valeur d'une fiche pour une colonne de tri ou de filtre. */
  function valeurDeTri(etablissement, cle) {
    if (cle === "region") return etablissement.region || REGION_VIDE;
    return etablissement[cle] || "";
  }

  /** Tri par la colonne courante ; le nom départage les valeurs égales. */
  function trier(etablissements) {
    var sens = etat.sens === "desc" ? -1 : 1;
    return etablissements.slice().sort(function (a, b) {
      var ecart = collateur.compare(valeurDeTri(a, etat.tri), valeurDeTri(b, etat.tri));
      // Sans départage, l'ordre des lignes changerait d'un rendu à l'autre et
      // une relecture du Sheet rebattrait le tableau sous les yeux du visiteur.
      if (ecart === 0 && etat.tri !== "nom") return collateur.compare(a.nom, b.nom);
      return ecart * sens;
    });
  }

  /** Reporte le tri courant sur les attributs aria-sort des en-têtes. */
  function majEntetes() {
    Array.prototype.slice.call(el.entetes).forEach(function (th) {
      var actif = th.dataset.tri === etat.tri;
      th.setAttribute(
        "aria-sort",
        actif ? (etat.sens === "desc" ? "descending" : "ascending") : "none"
      );
    });
  }

  /** Clic sur un en-tête : change de colonne, ou inverse le sens. */
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

  /** Remplit une liste déroulante ; chaque option porte son effectif. */
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

  /** Effectif de chaque valeur d'une colonne. */
  function comptesPar(cle) {
    return etat.tous.reduce(function (acc, etablissement) {
      var valeur = valeurDeTri(etablissement, cle);
      acc[valeur] = (acc[valeur] || 0) + 1;
      return acc;
    }, {});
  }

  /**
   * (Re)construit les deux listes déroulantes.
   * Les sélections en cours sont conservées : cette fonction est aussi appelée
   * après une relecture du Sheet.
   */
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

  /** Applique filtres et tri, met à jour le compteur, redessine le tableau. */
  function appliquer() {
    var recherche = pliage(el.recherche.value.trim());
    var region = el.region.value;
    var categorie = el.categorie.value;

    // Aucun filtre sélectionné = tout afficher.
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

    // La fiche sélectionnée peut être exclue par les filtres.
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

  /**
   * Clic sur un nom : signale la fiche à l'application hôte — qui peut par
   * exemple y centrer sa propre carte — et la souligne dans le tableau. On ne
   * quitte pas la page ; c'est le lien Google Maps qui ouvre un onglet.
   */
  function selectionner(id) {
    var etablissement = etat.tous[id];
    if (!etablissement) return;
    etat.selection = id;
    etat.selectionCle = etablissement.cle;

    Array.prototype.slice.call(el.lignes.querySelectorAll("tr")).forEach(function (tr) {
      tr.setAttribute("aria-current", tr.dataset.id === String(id) ? "true" : "false");
    });

    // Données publiques uniquement.
    var fiche = {
      nom: etablissement.nom,
      categorie: etablissement.categorie,
      region: etablissement.region,
      province: etablissement.province,
      lat: etablissement.lat,
      lon: etablissement.lon,
    };
    CHAMPS_FACULTATIFS.forEach(function (cle) {
      if (etablissement[cle]) fiche[cle] = etablissement[cle];
    });
    annoncer("selection", { etablissement: fiche });
  }

  /* ------------------------------- Chargement ------------------------------ */

  /**
   * Clé stable d'une fiche : identifie la même fiche d'une relecture à
   * l'autre. L'index, lui, se décale dès qu'une ligne est insérée dans le
   * Sheet.
   */
  function cleDe(e) {
    return [e.nom, e.province, e.lat, e.lon].join(" ");
  }

  /** Ajoute un identifiant et une clé stable à chaque fiche. */
  function indexer(etablissements) {
    return etablissements.map(function (e, index) {
      var fiche = {
        id: index,
        nom: e.nom,
        categorie: e.categorie,
        province: e.province,
        // Dans l'instantané, la région vient des polygones administratifs ;
        // pour une ligne relue en direct, de la table ville -> région.
        region: e.region || global.EARIARY_DONNEES.regionDe(e.province),
        lat: typeof e.lat === "number" ? e.lat : null,
        lon: typeof e.lon === "number" ? e.lon : null,
        coordonnees_brutes: e.coordonnees_brutes || "",
      };
      CHAMPS_FACULTATIFS.forEach(function (cle) {
        if (e[cle]) fiche[cle] = e[cle];
      });
      fiche.cle = cleDe(fiche);
      return fiche;
    });
  }

  /** Remplace le jeu de données affiché, en conservant l'état du visiteur. */
  function charger(donnees) {
    etat.tous = indexer(donnees.etablissements);
    etat.champs = donnees.champs || [];
    etat.source = donnees.source;

    // La fiche sélectionnée survit si elle est toujours dans le Sheet.
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

  /* ------------------------------- Démarrage ------------------------------- */

  function brancherEvenements() {
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
  }

  function demarrer() {
    if (options.theme !== "auto") {
      doc.documentElement.dataset.theme = options.theme;
    }
    el.app.dataset.header = options.entete ? "1" : "0";
    if (options.titre) el.titre.textContent = options.titre;
    el.recherche.value = options.recherche;
    majEntetes();
    brancherEvenements();

    // 1. Affichage immédiat de l'instantané embarqué.
    var snap = global.EARIARY_DONNEES.instantane();
    if (snap) charger(snap);

    // « pret » n'est envoyé qu'une fois, quelle que soit la source retenue.
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

    // 2. Relecture du Sheet, puis à intervalle régulier.
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
        // Échec silencieux : l'instantané reste affiché.
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
