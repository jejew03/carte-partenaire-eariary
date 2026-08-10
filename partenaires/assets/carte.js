/* Registre des partenaires eAriary — page carte.
 *
 * Carte, liste latérale et filtres. Le paramétrage passe par la chaîne de
 * requête de l'iframe (voir README) : l'application hôte n'a aucun script à
 * charger, aucun état à gérer.
 *
 * Les données viennent de `donnees.js` : l'instantané d'abord, puis le Google
 * Sheet relu et re-relu tant que la page reste ouverte. Un rafraîchissement
 * qui n'apporte rien de neuf ne redessine rien ; un qui apporte des lignes ne
 * doit ni recadrer la carte ni défaire la sélection du visiteur.
 */

(function (global) {
  "use strict";

  var L = global.L;
  var doc = global.document;

  /* Couleurs et glyphes vivent dans `categories.js`, que le tableau partage :
     un même type de commerce se lit pareil sur les deux pages. */
  function styleDe(categorie) {
    return global.EARIARY_CATEGORIES.styleDe(categorie);
  }

  /* ------------------------------ Paramètres ------------------------------ */

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

  /* Période de relecture du Sheet, en secondes. Plancher à 60 s : au-delà de
     ce rythme on interrogerait Google plus souvent que le Sheet ne change, et
     une iframe posée sur une page à fort trafic se ferait limiter. `0` fige la
     page sur ce qu'elle a chargé au démarrage. */
  function periode() {
    var brut = param("refresh", "300");
    var secondes = Number(brut);
    if (!isFinite(secondes) || secondes <= 0) return 0;
    return Math.max(secondes, 60) * 1000;
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
    periode: periode(),
    titre: param("titre", ""),
    recherche: param("q", ""),
    categories: liste("categorie"),
    provinces: liste("province"),
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
    source: "instantane",
    genereLe: "",
    majLe: null,
    onglet: "carte",
  };

  var el = {
    app: doc.getElementById("app"),
    titre: doc.getElementById("titre"),
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

  /* ------------------------------ Utilitaires ----------------------------- */

  function echapper(texte) {
    return String(texte).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var collateur = new Intl.Collator("fr", { sensitivity: "base", numeric: true });

  function trierFr(valeurs) {
    return valeurs.slice().sort(collateur.compare);
  }

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

  /* --------------------------- Champs facultatifs ------------------------- */
  /* Adresse, horaires, téléphone, site : absents du Sheet aujourd'hui. Chaque
     fonction ci-dessous ne produit quelque chose que si la valeur existe, si
     bien que la page est strictement identique tant que les colonnes ne sont
     pas remplies. */

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
    return texte.length > 34 ? texte.slice(0, 33) + "…" : texte;
  }

  var ICONE_EXTERNE =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M14 3v2h3.6l-9.8 9.8 1.4 1.4L19 6.4V10h2V3h-7Z"/>' +
    '<path d="M5 5h5V3H3v18h18v-7h-2v5H5V5Z"/></svg>';

  /* Liste de définitions des champs renseignés, ou chaîne vide s'il n'y en a
     aucun — auquel cas le popup n'affiche même pas le filet de séparation. */
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

  function initCarte() {
    // Madagascar en entier au démarrage ; fitBounds resserre dès qu'il y a des
    // points à montrer.
    carte = L.map("carte", {
      center: [-18.9, 46.9],
      zoom: 5,
      zoomControl: true,
      scrollWheelZoom: true,
      attributionControl: true,
    });

    // Fond accordé au thème : le fond clair de CARTO sous une interface sombre
    // éblouit et trahit un composant posé là sans y penser.
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

  /* `recadrer` est faux lors d'un rafraîchissement : le visiteur a peut-être
     zoomé sur un quartier, et lui reprendre son cadrage parce qu'une ligne a
     été ajoutée au Sheet à l'autre bout de l'île serait insupportable. */
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

  function dessinerListe() {
    el.liste.textContent = "";
    el.vide.hidden = etat.visibles.length > 0;

    // Groupé par ville, villes et établissements triés à la française.
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

  function dessinerFiltres() {
    // Villes
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

  function categoriesActives() {
    return Array.prototype.slice
      .call(el.chips.querySelectorAll('.chip[aria-pressed="true"]'))
      .map(function (chip) {
        return chip.dataset.categorie;
      });
  }

  function popupOuvert() {
    var marqueur = etat.selection === null ? null : marqueurs[etat.selection];
    return Boolean(marqueur && marqueur.isPopupOpen && marqueur.isPopupOpen());
  }

  function appliquer(reglages) {
    var recadrer = !reglages || reglages.recadrer !== false;
    var rouvrir = popupOuvert();

    var recherche = pliage(el.recherche.value.trim());
    var province = el.province.value;
    var categories = categoriesActives();
    el.chips.dataset.actives = categories.join("|");

    // Une sélection vide vaut « tout afficher » — même règle que l'application
    // interne.
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

    // Le popup rouvert n'est pas une nouveauté pour l'hôte : on le rétablit
    // sans réémettre de message « selection ».
    if (rouvrir && etat.selection !== null && marqueurs[etat.selection]) {
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

  function selectionner(id, opts) {
    etat.selection = id;
    var etablissement = etat.tous[id];
    etat.selectionCle = etablissement ? etablissement.cle : null;

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

    if (!etablissement) return;
    annoncer("selection", {
      etablissement: fichePublique(etablissement),
    });
  }

  /* Ce qui sort de l'iframe : des données publiques, et seulement les champs
     que le Sheet porte réellement. */
  function fichePublique(etablissement) {
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
    return fiche;
  }

  /* ---------------------------- Note de provenance ------------------------- */

  /* Une mention de source en pied de page, comme dans une publication : elle
     dit d'où viennent les chiffres et de quand ils datent. */
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
      return String(iso).slice(0, 10);
    }
  }

  function heure(date) {
    try {
      return new Intl.DateTimeFormat("fr-FR", {
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
    } catch (e) {
      return "";
    }
  }

  function majSource() {
    if (etat.source === "direct") {
      var h = etat.majLe ? heure(etat.majLe) : "";
      el.source.textContent =
        "Source : registre des partenaires eAriary" +
        (h ? ", mis à jour à " + h : ", consulté à l’instant") +
        ".";
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

  /* ------------------------------- Démarrage ------------------------------- */

  /* Clé stable d'une fiche : ce qui l'identifie indépendamment de sa position
     dans le Sheet. L'index, lui, se décale dès qu'une ligne est insérée. */
  function cleDe(e) {
    return [e.nom, e.province, e.lat, e.lon].join(" ");
  }

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
      ["adresse", "horaires", "telephone", "site"].forEach(function (cle) {
        if (e[cle]) fiche[cle] = e[cle];
      });
      fiche.cle = cleDe(fiche);
      return fiche;
    });
  }

  function charger(donnees, reglages) {
    var recadrer = !reglages || reglages.recadrer !== false;
    etat.tous = indexer(donnees.etablissements);
    etat.source = donnees.source;
    etat.genereLe = donnees.genereLe || "";
    if (donnees.source === "direct") etat.majLe = new Date();

    // La fiche sélectionnée survit au rafraîchissement si elle est toujours
    // dans le Sheet ; elle disparaît proprement sinon.
    etat.selection = null;
    if (etat.selectionCle) {
      etat.tous.forEach(function (e) {
        if (e.cle === etat.selectionCle) etat.selection = e.id;
      });
      if (etat.selection === null) etat.selectionCle = null;
    }

    majSource();
    dessinerFiltres();
    appliquer({ recadrer: recadrer });
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
    // la carte se dessine alors sur un conteneur de taille nulle et reste grise
    // jusqu'à ce qu'on la prévienne de sa nouvelle taille.
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(function () {
        if (carte) carte.invalidateSize();
      }).observe(doc.getElementById("carte"));
    }

    var snap = global.EARIARY_DONNEES.instantane();
    if (snap) charger(snap, { recadrer: true });

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
        // Au premier chargement la carte se cadre sur les points ; ensuite
        // jamais, pour ne pas reprendre au visiteur le cadrage qu'il a choisi.
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
        // Silencieux : l'instantané reste affiché, et la note de source dit
        // bien qu'il s'agit d'un relevé daté.
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
