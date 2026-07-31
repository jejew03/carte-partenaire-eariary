/* Iframe « établissements partenaires eAriary » — carte + liste.
 *
 * Le paramétrage passe par la chaîne de requête de l'iframe (voir README) :
 * l'application hôte n'a aucun script à charger, aucun état à gérer.
 */

(function (global) {
  "use strict";

  var L = global.L;
  var doc = global.document;

  /* --------------------------- Style par catégorie ----------------------- */
  /* Palette de catégories propre à la page publique : mêmes teintes de départ
     que `CATEGORY_STYLE` (app.py), mais ramenées à une clarté et une saturation
     communes pour former une série cohérente. Les couleurs vives d'origine
     viennent des marqueurs par défaut de Leaflet ; elles se voient comme telles.
     L'application Streamlit, à usage interne, garde les siennes.
     Chaque catégorie a aussi son glyphe : la couleur ne porte jamais seule
     l'information. Glyphes dans un carré de 13, dessinés en blanc. */
  var CATEGORIES = {
    Restaurant: {
      couleur: "#9E4038",
      glyphe:
        '<path d="M1.6 0h1.1v3.4h.8V0h1.1v3.4h.8V0h1.1v4.2c0 .9-.6 1.7-1.4 1.9V13H3V6.1C2.2 5.9 1.6 5.1 1.6 4.2V0z"/>' +
        '<path d="M9 0h1.6c.7 1.8 1 3.5.9 5.2 0 .6-.4 1-1 1.1V13H9.2V6.3c-.6-.1-1-.5-1-1.1C8.1 3.5 8.4 1.8 9 0z"/>',
    },
    "Hôtel": {
      couleur: "#2F5C86",
      glyphe:
        '<circle cx="3" cy="4.7" r="1.9"/>' +
        '<path d="M6 2.8h4.3c1.5 0 2.7 1.2 2.7 2.7v1.1H6V2.8z"/>' +
        '<path d="M0 7.4h13v2.1H0z"/><path d="M0 9.5h1.6V13H0zm11.4 0H13V13h-1.6z"/>',
    },
    Boutique: {
      couleur: "#4E7A3A",
      glyphe:
        '<path d="M6.5 0C4.8 0 3.4 1.4 3.4 3.1v.6H1.2L.3 13h12.4l-.9-9.3H9.6V3.1C9.6 1.4 8.2 0 6.5 0zm0 1.5c.9 0 1.6.7 1.6 1.6v.6H4.9V3.1c0-.9.7-1.6 1.6-1.6z"/>',
    },
    "Épicerie": {
      couleur: "#B0762A",
      glyphe:
        '<path d="M4 .3a.9.9 0 0 1 1.2.4L6.5 3.2 7.8.7A.9.9 0 1 1 9.4 1.5L8.2 3.7h3.9c.6 0 1.1.6.9 1.2l-1.9 7.2c-.1.5-.5.8-1 .8H2.9c-.5 0-.9-.3-1-.8L0 4.9c-.2-.6.3-1.2.9-1.2h3.9L3.6 1.5A.9.9 0 0 1 4 .3z"/>',
    },
    Magasin: {
      couleur: "#7A4A78",
      glyphe:
        '<path d="M0 0h13l-1 3.4H1L0 0z"/>' +
        '<path d="M1.4 4.6h10.2V13H8V8.7H5V13H1.4V4.6z"/>',
    },
    "Supermarché": {
      couleur: "#2F6F6A",
      glyphe:
        '<path d="M0 0h2.2l.5 1.9h9.4c.6 0 1 .6.8 1.1L11.3 8c-.1.4-.5.7-.9.7H4.3l.2.9h6.4v1.5H4c-.4 0-.8-.3-.9-.7L1.1 1.5H0V0z"/>' +
        '<circle cx="4.9" cy="12" r="1.1"/><circle cx="10.1" cy="12" r="1.1"/>',
    },
  };
  var DEFAUT = { couleur: "#6B6862", glyphe: '<circle cx="6.5" cy="6.5" r="3.4"/>' };

  function styleDe(categorie) {
    return CATEGORIES[categorie] || DEFAUT;
  }

  /* ------------------------------ Paramètres ----------------------------- */

  var params = new URLSearchParams(global.location.search);

  function param(nom, defaut) {
    var valeur = params.get(nom);
    return valeur === null || valeur === "" ? defaut : valeur;
  }

  function liste(nom) {
    return param(nom, "")
      .split(",")
      .map(function (v) {
        return v.trim();
      })
      .filter(Boolean);
  }

  var options = {
    vue: ["split", "carte", "liste"].indexOf(param("view", "split")) !== -1
      ? param("view", "split")
      : "split",
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
    categories: liste("categorie"),
    provinces: liste("province"),
    origine: param("origin", "*"),
  };

  /* --------------------------------- État -------------------------------- */

  var etat = {
    tous: [],
    visibles: [],
    selection: null, // index dans `tous`
    source: "instantane",
    genereLe: "",
    onglet: "carte",
  };

  var el = {
    app: doc.getElementById("app"),
    titre: doc.getElementById("titre"),
    sous: doc.getElementById("sous-titre"),
    source: doc.getElementById("source"),
    recherche: doc.getElementById("recherche"),
    province: doc.getElementById("province"),
    chips: doc.getElementById("chips"),
    compte: doc.getElementById("compte"),
    reset: doc.getElementById("reset"),
    liste: doc.getElementById("liste"),
    vide: doc.getElementById("vide"),
    onglets: doc.getElementById("onglets"),
  };

  var carte = null;
  var couche = null;
  var marqueurs = {}; // index dans `tous` -> L.Marker

  /* ------------------------------- Utilitaires --------------------------- */

  function echapper(texte) {
    return String(texte).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var collateur = new Intl.Collator("fr", { sensitivity: "base", numeric: true });

  function trierFr(valeurs) {
    return valeurs.slice().sort(collateur.compare);
  }

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
    var message = { source: "eariary-embed", type: type };
    Object.keys(charge || {}).forEach(function (cle) {
      message[cle] = charge[cle];
    });
    try {
      global.parent.postMessage(message, options.origine);
    } catch (e) {
      /* origine refusée par l'hôte : l'iframe reste fonctionnelle sans. */
    }
  }

  /* --------------------------------- Carte ------------------------------- */

  /* Disque cerné de blanc, centré sur le point : un symbole de carte, là où la
     goutte évoque une application de navigation. La fiche sélectionnée grossit
     et prend un cercle d'encre — un changement de taille et de forme, pas
     seulement de couleur. */
  function icone(etablissement, actif) {
    var style = styleDe(etablissement.categorie);
    var taille = actif ? 30 : 24;
    var centre = taille / 2;
    var echelle = actif ? 0.82 : 0.66;
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
      '<div class="coords">' +
      etablissement.lat.toFixed(6) +
      ", " +
      etablissement.lon.toFixed(6) +
      "</div>" +
      '<a class="gmaps" href="https://www.google.com/maps?q=' +
      etablissement.lat +
      "," +
      etablissement.lon +
      '" target="_blank" rel="noopener">Ouvrir dans Google Maps</a>' +
      "</div>"
    );
  }

  function initCarte() {
    // Madagascar en entier au démarrage ; fitBounds resserre dès qu'il y a
    // des points à montrer.
    carte = L.map("carte", {
      center: [-18.9, 46.9],
      zoom: 5,
      zoomControl: true,
      scrollWheelZoom: true,
      attributionControl: true,
    });

    // Fond sobre accordé au thème : le fond clair de CARTO sous une interface
    // sombre éblouit et trahit un composant posé là sans y penser.
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
      .layers(
        { Plan: plan, "Plan détaillé": detaille, Satellite: satellite },
        null,
        { position: "topright" }
      )
      .addTo(carte);
    L.control.scale({ imperial: false, position: "bottomleft" }).addTo(carte);

    couche = L.layerGroup().addTo(carte);
  }

  function dessinerCarte() {
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
        .bindPopup(popup(etablissement), { maxWidth: 300, autoPanPadding: [24, 24] })
        .on("click", function () {
          selectionner(etablissement.id, { ouvrirPopup: false, recentrer: false });
        });
      marqueur.addTo(couche);
      marqueurs[etablissement.id] = marqueur;
      coordonnees.push([etablissement.lat, etablissement.lon]);
    });

    if (coordonnees.length > 1) {
      carte.fitBounds(L.latLngBounds(coordonnees), { padding: [40, 40], maxZoom: 14 });
    } else if (coordonnees.length === 1) {
      carte.setView(coordonnees[0], 14);
    }
  }

  /* --------------------------------- Liste ------------------------------- */

  function ligne(etablissement) {
    var style = styleDe(etablissement.categorie);
    var bouton = doc.createElement("button");
    bouton.type = "button";
    bouton.className = "item";
    bouton.dataset.id = String(etablissement.id);
    bouton.setAttribute("aria-current", etablissement.id === etat.selection ? "true" : "false");

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
      sansPoint;

    bouton.addEventListener("click", function () {
      selectionner(etablissement.id, { ouvrirPopup: true, recentrer: true });
    });
    return bouton;
  }

  function dessinerListe() {
    el.liste.textContent = "";
    el.vide.hidden = etat.visibles.length > 0;

    // Groupé par province, provinces et établissements triés à la française.
    var parProvince = {};
    etat.visibles.forEach(function (etablissement) {
      (parProvince[etablissement.province] =
        parProvince[etablissement.province] || []).push(etablissement);
    });

    trierFr(Object.keys(parProvince)).forEach(function (province) {
      var titre = doc.createElement("div");
      titre.className = "group";
      titre.innerHTML =
        '<span class="eyebrow">' +
        echapper(province) +
        '</span><span class="n">' +
        parProvince[province].length +
        "</span>";
      el.liste.appendChild(titre);

      parProvince[province]
        .slice()
        .sort(function (a, b) {
          return collateur.compare(a.nom, b.nom);
        })
        .forEach(function (etablissement) {
          el.liste.appendChild(ligne(etablissement));
        });
    });
  }

  /* -------------------------------- Filtres ------------------------------ */

  function dessinerFiltres() {
    // Provinces
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

    // Puces de catégorie : filtre et légende à la fois.
    var comptes = etat.tous.reduce(function (acc, e) {
      acc[e.categorie] = (acc[e.categorie] || 0) + 1;
      return acc;
    }, {});
    var actives = el.chips.dataset.actives
      ? el.chips.dataset.actives.split("|")
      : options.categories;
    el.chips.textContent = "";
    trierFr(Object.keys(comptes)).forEach(function (categorie) {
      var style = styleDe(categorie);
      var chip = doc.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.dataset.categorie = categorie;
      chip.setAttribute("aria-pressed", actives.indexOf(categorie) !== -1 ? "true" : "false");
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

  function categoriesActives() {
    return Array.prototype.slice
      .call(el.chips.querySelectorAll('.chip[aria-pressed="true"]'))
      .map(function (chip) {
        return chip.dataset.categorie;
      });
  }

  function appliquer() {
    var recherche = pliage(el.recherche.value.trim());
    var province = el.province.value;
    var categories = categoriesActives();
    el.chips.dataset.actives = categories.join("|");

    // Une sélection vide vaut « tout afficher » — même règle que l'app.
    etat.visibles = etat.tous.filter(function (e) {
      if (province && e.province !== province) return false;
      if (categories.length && categories.indexOf(e.categorie) === -1) return false;
      if (
        recherche &&
        pliage(e.nom).indexOf(recherche) === -1 &&
        pliage(e.province).indexOf(recherche) === -1 &&
        pliage(e.categorie).indexOf(recherche) === -1
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

    var filtre = Boolean(recherche || province || categories.length);
    el.reset.hidden = !filtre;

    if (
      etat.selection !== null &&
      !etat.visibles.some(function (e) {
        return e.id === etat.selection;
      })
    ) {
      etat.selection = null;
    }

    dessinerListe();
    dessinerCarte();
    annoncer("filtre", {
      visibles: etat.visibles.length,
      recherche: el.recherche.value.trim(),
      province: province,
      categories: categories,
    });
  }

  /* ------------------------------ Sélection ------------------------------ */

  function selectionner(id, opts) {
    etat.selection = id;
    var etablissement = etat.tous[id];

    Array.prototype.slice.call(el.liste.querySelectorAll(".item")).forEach(function (item) {
      var actif = item.dataset.id === String(id);
      item.setAttribute("aria-current", actif ? "true" : "false");
      // Le clic peut venir d'un marqueur : la liste suit la carte, et
      // inversement, pour que les deux vues désignent toujours la même fiche.
      if (actif) item.scrollIntoView({ block: "nearest" });
    });

    Object.keys(marqueurs).forEach(function (cle) {
      var index = Number(cle);
      marqueurs[cle].setIcon(icone(etat.tous[index], index === id));
    });

    var marqueur = marqueurs[id];
    if (marqueur) {
      // En écran étroit, la carte peut être masquée : on l'affiche d'abord.
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

    annoncer("selection", {
      etablissement: {
        nom: etablissement.nom,
        categorie: etablissement.categorie,
        province: etablissement.province,
        lat: etablissement.lat,
        lon: etablissement.lon,
      },
    });
  }

  /* --------------------------- Note de provenance ------------------------ */

  /* Une mention de source en pied de page, comme dans une publication : elle
     dit d'où viennent les chiffres et de quand ils datent. C'est la même
     information que l'ancienne pastille « Instantané / Données à jour », mais
     écrite pour le public plutôt que pour l'exploitant. */
  function dateLongue(iso) {
    var date = new Date(iso);
    if (isNaN(date.getTime())) return "";
    try {
      return new Intl.DateTimeFormat("fr-FR", {
        day: "numeric",
        month: "long",
        year: "numeric",
      }).format(date);
    } catch (e) {
      return iso.slice(0, 10);
    }
  }

  function majSource() {
    if (etat.source === "direct") {
      el.source.textContent =
        "Source : registre des partenaires eAriary, consulté à l’instant.";
      return;
    }
    var jour = etat.genereLe ? dateLongue(etat.genereLe) : "";
    el.source.textContent =
      "Source : registre des partenaires eAriary" +
      (jour ? ", relevé du " + jour : "") +
      ".";
  }

  function basculer(onglet) {
    etat.onglet = onglet;
    el.app.dataset.onglet = onglet;
    Array.prototype.slice.call(el.onglets.querySelectorAll("button")).forEach(function (b) {
      b.setAttribute("aria-selected", b.dataset.onglet === onglet ? "true" : "false");
    });
    if (onglet === "carte" && carte) carte.invalidateSize();
  }

  /* ------------------------------ Démarrage ------------------------------ */

  function indexer(etablissements) {
    return etablissements.map(function (e, index) {
      return {
        id: index,
        nom: e.nom,
        categorie: e.categorie,
        province: e.province,
        lat: typeof e.lat === "number" ? e.lat : null,
        lon: typeof e.lon === "number" ? e.lon : null,
        coordonnees_brutes: e.coordonnees_brutes || "",
      };
    });
  }

  function charger(donnees) {
    etat.tous = indexer(donnees.etablissements);
    etat.source = donnees.source;
    etat.genereLe = donnees.genereLe || "";
    etat.selection = null;
    majSource();
    dessinerFiltres();
    appliquer();
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

    el.recherche.addEventListener("input", appliquer);
    el.province.addEventListener("change", appliquer);
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
    // la carte se dessine alors sur un conteneur de taille nulle et reste
    // grise jusqu'à ce qu'on la prévienne de sa nouvelle taille.
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(function () {
        if (carte) carte.invalidateSize();
      }).observe(doc.getElementById("carte"));
    }

    var snap = global.EARIARY_DATA.instantane();
    if (snap) charger(snap);

    var termine = function () {
      annoncer("pret", {
        total: etat.tous.length,
        visibles: etat.visibles.length,
        source: etat.source,
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
        // Silencieux : l'instantané reste affiché, la note de source le dit.
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
