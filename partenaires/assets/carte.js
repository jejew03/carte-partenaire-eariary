/* Page carte : carte Leaflet + liste latérale + filtres.
 *
 * Dépendances chargées avant ce fichier (voir carte.html) :
 *   vendor/leaflet/leaflet.js   la carte
 *   assets/instantane.js        window.EARIARY_PARTENAIRES
 *   assets/categories.js        window.EARIARY_CATEGORIES
 *   assets/donnees.js           window.EARIARY_DONNEES
 *
 * Le paramétrage se fait par la chaîne de requête de l'iframe (voir README) :
 * l'application hôte n'a aucun script à charger ni état à gérer.
 *
 * Écrit en ES5 (var, pas de classes) : ces pages sont intégrées dans des
 * applications tierces dont on ne maîtrise pas le parc de navigateurs.
 */

(function (global) {
  "use strict";

  var L = global.L;
  var doc = global.document;

  // Champs facultatifs du Sheet, présents dans une fiche seulement s'ils sont
  // renseignés. Ordre d'affichage dans le popup.
  var CHAMPS_FACULTATIFS = ["adresse", "horaires", "telephone", "site"];

  /* ------------------------------ Paramètres ------------------------------ */

  var params = new URLSearchParams(global.location.search);

  /** Valeur d'un paramètre d'URL, ou `defaut` s'il est absent ou vide. */
  function param(nom, defaut) {
    var valeur = params.get(nom);
    return valeur === null || valeur === "" ? defaut : valeur;
  }

  /** Paramètre lu comme une liste séparée par des virgules. */
  function liste(nom) {
    return param(nom, "")
      .split(",")
      .map(function (v) {
        return v.trim();
      })
      .filter(Boolean);
  }

  /** Valeur si elle fait partie des valeurs admises, sinon la première. */
  function parmi(nom, admises) {
    var valeur = param(nom, admises[0]);
    return admises.indexOf(valeur) !== -1 ? valeur : admises[0];
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
    vue: parmi("view", ["split", "carte", "liste"]),
    entete: param("header", "1") !== "0",
    // Thème clair par défaut : la page est un document public, son apparence
    // ne doit pas dépendre du réglage système du visiteur. `theme=auto` le
    // rétablit.
    theme: parmi("theme", ["clair", "sombre", "auto"]),
    direct: param("live", "1") !== "0",
    periode: periode(),
    titre: param("titre", ""),
    recherche: param("q", ""),
    categories: liste("categorie"),
    provinces: liste("province"),
    origine: param("origin", "*"),
  };

  /* --------------------------------- État --------------------------------- */

  var etat = {
    tous: [], // toutes les fiches
    visibles: [], // fiches retenues par les filtres
    selection: null, // index dans `tous`, ou null
    selectionCle: null, // clé stable de la fiche sélectionnée (voir cleDe)
    source: "instantane", // "instantane" ou "direct"
    onglet: "carte", // onglet actif en écran étroit
  };

  var el = {
    app: doc.getElementById("app"),
    titre: doc.getElementById("titre"),
    recherche: doc.getElementById("recherche"),
    province: doc.getElementById("province"),
    chips: doc.getElementById("chips"),
    compte: doc.getElementById("compte"),
    reset: doc.getElementById("reset"),
    liste: doc.getElementById("liste"),
    vide: doc.getElementById("vide"),
    onglets: doc.getElementById("onglets"),
  };

  var carte = null; // L.Map
  var couche = null; // L.LayerGroup contenant les repères
  var marqueurs = {}; // index dans `tous` -> L.Marker

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

  /** Tri alphabétique français (accents ignorés). */
  function trierFr(valeurs) {
    return valeurs.slice().sort(collateur.compare);
  }

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

  /* --------------------------- Champs facultatifs ------------------------- */

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
    return texte.length > 34 ? texte.slice(0, 33) + "…" : texte;
  }

  var ICONE_EXTERNE =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M14 3v2h3.6l-9.8 9.8 1.4 1.4L19 6.4V10h2V3h-7Z"/>' +
    '<path d="M5 5h5V3H3v18h18v-7h-2v5H5V5Z"/></svg>';

  /**
   * Bloc <dl> des champs facultatifs renseignés, ou "" s'il n'y en a aucun —
   * auquel cas le popup n'affiche même pas le filet de séparation.
   */
  function ficheHtml(etablissement) {
    var lignes = [];
    if (etablissement.adresse) {
      lignes.push(["Adresse", echapper(etablissement.adresse)]);
    }
    if (etablissement.horaires) {
      lignes.push(["Horaires", echapper(etablissement.horaires)]);
    }
    if (etablissement.telephone) {
      lignes.push([
        "Téléphone",
        '<a href="' +
          echapper(telHref(etablissement.telephone)) +
          '">' +
          echapper(etablissement.telephone) +
          "</a>",
      ]);
    }
    if (etablissement.site) {
      lignes.push([
        "Site",
        '<a href="' +
          echapper(siteHref(etablissement.site)) +
          '" target="_blank" rel="noopener">' +
          echapper(libelleSite(etablissement.site)) +
          "</a>",
      ]);
    }
    if (!lignes.length) return "";
    return (
      '<dl class="fiche">' +
      lignes
        .map(function (paire) {
          return "<dt>" + paire[0] + "</dt><dd>" + paire[1] + "</dd>";
        })
        .join("") +
      "</dl>"
    );
  }

  /* --------------------------------- Carte -------------------------------- */

  /**
   * Repère de carte : disque coloré cerné de blanc, avec le glyphe de la
   * catégorie. Le repère sélectionné est plus grand et cerné d'un anneau : la
   * sélection se voit à la taille et à la forme, pas seulement à la couleur.
   */
  function icone(etablissement, actif) {
    var style = styleDe(etablissement.categorie);
    var taille = actif ? 30 : 24;
    var centre = taille / 2;
    var echelle = actif ? 0.82 : 0.66; // les glyphes sont dessinés dans 13 × 13
    var decalage = (taille - 13 * echelle) / 2;
    var svg =
      '<svg width="' + taille + '" height="' + taille + '" viewBox="0 0 ' +
      taille + " " + taille + '" aria-hidden="true">' +
      (actif
        ? '<circle class="ring" cx="' + centre + '" cy="' + centre + '" r="' +
          (centre - 0.75) + '" fill="none" stroke-width="1.5"/>'
        : "") +
      '<circle cx="' + centre + '" cy="' + centre + '" r="' + (centre - 2.75) +
      '" fill="' + style.couleur + '" stroke="#ffffff" stroke-width="2"/>' +
      '<g transform="translate(' + decalage.toFixed(2) + " " +
      decalage.toFixed(2) + ") scale(" + echelle + ')" fill="#ffffff">' +
      style.glyphe +
      "</g></svg>";
    return L.divIcon({
      className: "pin" + (actif ? " on" : ""),
      html: svg,
      iconSize: [taille, taille],
      iconAnchor: [centre, centre],
      popupAnchor: [0, -centre - 1],
    });
  }

  /** Contenu du popup d'un repère. */
  function popup(etablissement) {
    var style = styleDe(etablissement.categorie);
    return (
      '<div class="pop">' +
      '<div class="nom">' +
      echapper(etablissement.nom) +
      "</div>" +
      '<div class="tag"><span class="swatch" style="background:' +
      style.couleur +
      '"></span>' +
      echapper(etablissement.categorie) +
      "</div>" +
      '<div class="prov">' +
      echapper(etablissement.province) +
      "</div>" +
      ficheHtml(etablissement) +
      '<div class="coords">' +
      etablissement.lat.toFixed(6) +
      ", " +
      etablissement.lon.toFixed(6) +
      "</div>" +
      '<a class="lien" href="https://www.google.com/maps?q=' +
      etablissement.lat +
      "," +
      etablissement.lon +
      '" target="_blank" rel="noopener">Ouvrir dans Google Maps' +
      ICONE_EXTERNE +
      "</a>" +
      "</div>"
    );
  }

  /** Crée la carte, ses fonds et le groupe de repères. */
  function initCarte() {
    // Vue initiale : Madagascar en entier. `dessinerCarte` resserre ensuite.
    carte = L.map("carte", {
      center: [-18.9, 46.9],
      zoom: 5,
      zoomControl: true,
      scrollWheelZoom: true,
      attributionControl: true,
    });

    // Fond assorti au thème : un fond clair sous une interface sombre éblouit.
    var sombre =
      doc.documentElement.dataset.theme === "sombre" ||
      (options.theme === "auto" &&
        typeof global.matchMedia === "function" &&
        global.matchMedia("(prefers-color-scheme: dark)").matches);

    var plan = L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/" +
        (sombre ? "dark_all" : "light_all") +
        "/{z}/{x}/{y}{r}.png",
      {
        maxZoom: 19,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>, &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>',
      }
    ).addTo(carte);

    var detaille = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
    });

    var satellite = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 19, attribution: "Esri, Maxar, Earthstar Geographics" }
    );

    L.control
      .layers({ Plan: plan, "Plan détaillé": detaille, Satellite: satellite }, null, {
        position: "topright",
      })
      .addTo(carte);
    L.control.scale({ imperial: false, position: "bottomleft" }).addTo(carte);

    couche = L.layerGroup().addTo(carte);
  }

  /**
   * Redessine les repères des fiches visibles.
   * `recadrer` vaut false lors d'une relecture du Sheet : le visiteur a pu
   * zoomer, on ne lui reprend pas son cadrage.
   */
  function dessinerCarte(recadrer) {
    couche.clearLayers();
    marqueurs = {};

    var coordonnees = [];
    etat.visibles.forEach(function (etablissement) {
      if (etablissement.lat === null || etablissement.lon === null) return;
      var marqueur = L.marker([etablissement.lat, etablissement.lon], {
        icon: icone(etablissement, etablissement.id === etat.selection),
        title: etablissement.nom,
        alt: etablissement.nom + " — " + etablissement.categorie,
        riseOnHover: true,
      })
        .bindPopup(popup(etablissement), { maxWidth: 320, autoPanPadding: [24, 24] })
        .on("click", function () {
          selectionner(etablissement.id, { ouvrirPopup: false, recentrer: false });
        });
      marqueur.addTo(couche);
      marqueurs[etablissement.id] = marqueur;
      coordonnees.push([etablissement.lat, etablissement.lon]);
    });

    if (!recadrer) return;
    if (coordonnees.length > 1) {
      carte.fitBounds(L.latLngBounds(coordonnees), { padding: [40, 40], maxZoom: 14 });
    } else if (coordonnees.length === 1) {
      carte.setView(coordonnees[0], 14);
    }
  }

  /* --------------------------------- Liste -------------------------------- */

  /** Adresse et téléphone sous la ligne de métadonnées, s'ils existent. */
  function infosHtml(etablissement) {
    var champs = [];
    if (etablissement.adresse) {
      champs.push('<span class="champ">' + echapper(etablissement.adresse) + "</span>");
    }
    if (etablissement.telephone) {
      champs.push('<span class="champ">' + echapper(etablissement.telephone) + "</span>");
    }
    return champs.length ? '<div class="infos">' + champs.join("") + "</div>" : "";
  }

  /** Une fiche de la liste latérale. C'est un <button> : navigable au clavier. */
  function ligne(etablissement) {
    var style = styleDe(etablissement.categorie);
    var bouton = doc.createElement("button");
    bouton.type = "button";
    bouton.className = "item";
    bouton.dataset.id = String(etablissement.id);
    bouton.setAttribute(
      "aria-current",
      etablissement.id === etat.selection ? "true" : "false"
    );

    // Une fiche sans coordonnées reste dans la liste, mais n'a pas de repère.
    var sansPoint =
      etablissement.lat === null
        ? '<div class="warn">Coordonnées indisponibles' +
          (etablissement.coordonnees_brutes
            ? " — « " + echapper(etablissement.coordonnees_brutes) + " »"
            : "") +
          "</div>"
        : "";

    bouton.innerHTML =
      '<div class="nom">' +
      echapper(etablissement.nom) +
      "</div>" +
      '<div class="meta">' +
      '<span class="swatch" style="background:' +
      style.couleur +
      '"></span>' +
      echapper(etablissement.categorie) +
      '<span class="sep" aria-hidden="true">·</span>' +
      echapper(etablissement.province) +
      "</div>" +
      infosHtml(etablissement) +
      sansPoint;

    bouton.addEventListener("click", function () {
      selectionner(etablissement.id, { ouvrirPopup: true, recentrer: true });
    });
    return bouton;
  }

  /** Redessine la liste, groupée par ville. */
  function dessinerListe() {
    el.liste.textContent = "";
    el.vide.hidden = etat.visibles.length > 0;

    var parProvince = {};
    etat.visibles.forEach(function (etablissement) {
      (parProvince[etablissement.province] =
        parProvince[etablissement.province] || []).push(etablissement);
    });

    var fragment = doc.createDocumentFragment();
    trierFr(Object.keys(parProvince)).forEach(function (province) {
      var titre = doc.createElement("div");
      titre.className = "group";
      titre.innerHTML =
        '<span class="eyebrow">' +
        echapper(province) +
        '</span><span class="n">' +
        parProvince[province].length +
        "</span>";
      fragment.appendChild(titre);

      parProvince[province]
        .slice()
        .sort(function (a, b) {
          return collateur.compare(a.nom, b.nom);
        })
        .forEach(function (etablissement) {
          fragment.appendChild(ligne(etablissement));
        });
    });
    el.liste.appendChild(fragment);
  }

  /* -------------------------------- Filtres -------------------------------- */

  /**
   * (Re)construit la liste des villes et les puces de catégorie.
   * Les sélections en cours sont conservées : cette fonction est aussi appelée
   * après une relecture du Sheet.
   */
  function dessinerFiltres() {
    var provinces = trierFr(
      Object.keys(
        etat.tous.reduce(function (acc, e) {
          acc[e.province] = true;
          return acc;
        }, {})
      )
    );
    var choisie = el.province.value;
    el.province.textContent = "";
    var toutes = doc.createElement("option");
    toutes.value = "";
    toutes.textContent = "Toutes les villes";
    el.province.appendChild(toutes);
    provinces.forEach(function (province) {
      var option = doc.createElement("option");
      option.value = province;
      option.textContent = province;
      el.province.appendChild(option);
    });
    if (options.provinces.length === 1 && !choisie) choisie = options.provinces[0];
    el.province.value = provinces.indexOf(choisie) !== -1 ? choisie : "";

    // Les puces servent de filtre ET de légende : elles portent l'effectif de
    // chaque catégorie.
    var comptes = etat.tous.reduce(function (acc, e) {
      acc[e.categorie] = (acc[e.categorie] || 0) + 1;
      return acc;
    }, {});
    var actives = el.chips.dataset.actives
      ? el.chips.dataset.actives.split("|").filter(Boolean)
      : options.categories;
    el.chips.textContent = "";
    trierFr(Object.keys(comptes)).forEach(function (categorie) {
      var style = styleDe(categorie);
      var chip = doc.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.dataset.categorie = categorie;
      chip.setAttribute(
        "aria-pressed",
        actives.indexOf(categorie) !== -1 ? "true" : "false"
      );
      chip.innerHTML =
        '<span class="swatch" style="background:' +
        style.couleur +
        '"></span>' +
        echapper(categorie) +
        '<span class="n">' +
        comptes[categorie] +
        "</span>";
      chip.addEventListener("click", function () {
        var actif = chip.getAttribute("aria-pressed") === "true";
        chip.setAttribute("aria-pressed", actif ? "false" : "true");
        appliquer();
      });
      el.chips.appendChild(chip);
    });
  }

  /** Catégories actuellement sélectionnées. */
  function categoriesActives() {
    return Array.prototype.slice
      .call(el.chips.querySelectorAll('.chip[aria-pressed="true"]'))
      .map(function (chip) {
        return chip.dataset.categorie;
      });
  }

  /** Le popup de la fiche sélectionnée est-il ouvert ? */
  function popupOuvert() {
    var marqueur = etat.selection === null ? null : marqueurs[etat.selection];
    return Boolean(marqueur && marqueur.isPopupOpen && marqueur.isPopupOpen());
  }

  /**
   * Applique les filtres, met à jour le compteur, redessine liste et carte.
   * `reglages.recadrer` vaut false lors d'une relecture du Sheet.
   */
  function appliquer(reglages) {
    var recadrer = !reglages || reglages.recadrer !== false;
    var rouvrirPopup = popupOuvert();

    var recherche = pliage(el.recherche.value.trim());
    var province = el.province.value;
    var categories = categoriesActives();
    el.chips.dataset.actives = categories.join("|");

    // Aucun filtre sélectionné = tout afficher.
    etat.visibles = etat.tous.filter(function (e) {
      if (province && e.province !== province) return false;
      if (categories.length && categories.indexOf(e.categorie) === -1) return false;
      if (
        recherche &&
        pliage(e.nom).indexOf(recherche) === -1 &&
        pliage(e.province).indexOf(recherche) === -1 &&
        pliage(e.categorie).indexOf(recherche) === -1 &&
        pliage(e.adresse || "").indexOf(recherche) === -1
      ) {
        return false;
      }
      return true;
    });

    var localises = etat.visibles.filter(function (e) {
      return e.lat !== null;
    }).length;
    el.compte.textContent =
      etat.visibles.length +
      (etat.visibles.length > 1 ? " établissements" : " établissement") +
      (localises !== etat.visibles.length ? " — " + localises + " sur la carte" : "");

    el.reset.hidden = !(recherche || province || categories.length);

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

    dessinerListe();
    dessinerCarte(recadrer);

    // Rouvrir un popup n'est pas une nouvelle sélection : pas de message.
    if (rouvrirPopup && etat.selection !== null && marqueurs[etat.selection]) {
      marqueurs[etat.selection].openPopup();
    }

    annoncer("filtre", {
      visibles: etat.visibles.length,
      recherche: el.recherche.value.trim(),
      province: province,
      categories: categories,
    });
  }

  /* ------------------------------- Sélection ------------------------------- */

  /** Champs transmis à l'application hôte (données publiques uniquement). */
  function fichePublique(etablissement) {
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
    return fiche;
  }

  /**
   * Sélectionne une fiche : liste et carte désignent toujours la même.
   * `opts.recentrer` déplace la carte, `opts.ouvrirPopup` ouvre le popup.
   */
  function selectionner(id, opts) {
    var etablissement = etat.tous[id];
    if (!etablissement) return;
    etat.selection = id;
    etat.selectionCle = etablissement.cle;

    Array.prototype.slice.call(el.liste.querySelectorAll(".item")).forEach(function (item) {
      var actif = item.dataset.id === String(id);
      item.setAttribute("aria-current", actif ? "true" : "false");
      if (actif) item.scrollIntoView({ block: "nearest" });
    });

    Object.keys(marqueurs).forEach(function (cle) {
      var index = Number(cle);
      marqueurs[cle].setIcon(icone(etat.tous[index], index === id));
    });

    var marqueur = marqueurs[id];
    if (marqueur) {
      // En écran étroit, la carte peut être masquée par l'onglet « Liste ».
      if (el.app.dataset.view === "split" && el.app.dataset.onglet === "liste") {
        basculer("carte");
      }
      if (opts && opts.recentrer) {
        carte.flyTo(marqueur.getLatLng(), Math.max(carte.getZoom(), 13), {
          duration: 0.6,
        });
      }
      if (!opts || opts.ouvrirPopup !== false) marqueur.openPopup();
    }

    annoncer("selection", { etablissement: fichePublique(etablissement) });
  }

  /** Bascule entre les onglets Carte et Liste (écran étroit uniquement). */
  function basculer(onglet) {
    etat.onglet = onglet;
    el.app.dataset.onglet = onglet;
    Array.prototype.slice.call(el.onglets.querySelectorAll("button")).forEach(function (b) {
      b.setAttribute("aria-selected", b.dataset.onglet === onglet ? "true" : "false");
    });
    if (onglet === "carte" && carte) carte.invalidateSize();
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
  function charger(donnees, reglages) {
    var recadrer = !reglages || reglages.recadrer !== false;
    etat.tous = indexer(donnees.etablissements);
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
    appliquer({ recadrer: recadrer });
  }

  /* ------------------------------- Démarrage ------------------------------- */

  function brancherEvenements() {
    el.recherche.addEventListener("input", function () {
      appliquer();
    });
    el.province.addEventListener("change", function () {
      appliquer();
    });
    el.reset.addEventListener("click", function () {
      el.recherche.value = "";
      el.province.value = "";
      Array.prototype.slice.call(el.chips.querySelectorAll(".chip")).forEach(function (chip) {
        chip.setAttribute("aria-pressed", "false");
      });
      appliquer();
      el.recherche.focus();
    });
    Array.prototype.slice.call(el.onglets.querySelectorAll("button")).forEach(function (b) {
      b.addEventListener("click", function () {
        basculer(b.dataset.onglet);
      });
    });

    global.addEventListener("resize", function () {
      if (carte) carte.invalidateSize();
    });
    // L'iframe peut être posée dans un onglet masqué de l'application hôte :
    // la carte se dessine alors dans un conteneur de taille nulle et reste
    // grise tant qu'on ne la prévient pas de sa nouvelle taille.
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(function () {
        if (carte) carte.invalidateSize();
      }).observe(doc.getElementById("carte"));
    }
  }

  function demarrer() {
    if (options.theme !== "auto") {
      doc.documentElement.dataset.theme = options.theme;
    }
    el.app.dataset.view = options.vue;
    el.app.dataset.header = options.entete ? "1" : "0";
    el.app.dataset.onglet = "carte";
    if (options.titre) el.titre.textContent = options.titre;
    el.recherche.value = options.recherche;
    el.chips.dataset.actives = options.categories.join("|");

    initCarte();
    brancherEvenements();

    // 1. Affichage immédiat de l'instantané embarqué.
    var snap = global.EARIARY_DONNEES.instantane();
    if (snap) charger(snap, { recadrer: true });

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
        // On ne cadre la carte qu'au tout premier affichage.
        charger(donnees, { recadrer: contexte.premier && !snap });
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
