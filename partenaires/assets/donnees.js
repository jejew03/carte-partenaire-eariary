/* Registre des partenaires eAriary — accès aux données.
 *
 * Deux sources, dans cet ordre :
 *   1. `window.EARIARY_PARTENAIRES` — l'instantané versionné
 *      (`assets/instantane.js`), affiché tout de suite, sans attendre le
 *      réseau ;
 *   2. le Google Sheet, relu dans le navigateur, qui remplace l'instantané dès
 *      qu'il répond, puis à intervalle régulier tant que la page reste
 *      ouverte. Un échec — Sheet redevenu privé, hors ligne, politique de
 *      sécurité de l'application hôte — est silencieux : la page continue
 *      d'afficher ce qu'elle a.
 *
 * Les règles de nettoyage reproduisent celles de `build.py` : même détection
 * d'en-tête, mêmes mots-clés de colonnes, mêmes corrections de libellés. Les
 * deux fichiers évoluent ensemble.
 */

(function (global) {
  "use strict";

  var SHEET_ID = "1D15egjrBB_9eNCXC-THxZcSqvNtf7ttfssdcVDRu8Yo";
  var GID = "0";
  // Endpoint gviz plutôt que /export : il répond avec un en-tête CORS sans
  // redirection, donc lisible en fetch() depuis n'importe quelle origine.
  var SHEET_URL =
    "https://docs.google.com/spreadsheets/d/" +
    SHEET_ID +
    "/gviz/tq?tqx=out:csv&gid=" +
    GID;

  var COORD_RE = /^\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*[,;]\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*$/;

  /* Colonnes attendues : clé, mots-clés d'en-tête, position de repli. Le repli
     ne sert que si aucun mot-clé ne correspond ; une colonne trouvée en
     position 0 doit être retenue telle quelle, d'où un indice explicite. */
  var COLONNES = [
    { cle: "province", mots: ["province", "ville", "region"], defaut: 0 },
    { cle: "nom", mots: ["etablissement", "enseigne", "nom"], defaut: 1 },
    { cle: "categorie", mots: ["categorie", "type"], defaut: 2 },
    { cle: "coordonnees", mots: ["latitude", "longitude", "coord", "gps"], defaut: 3 },
  ];

  /* Colonnes facultatives, absentes du Sheet à ce jour. Le jour où l'une y est
     ajoutée, elle apparaît d'elle-même dans les pages. Aucun repli de
     position : une colonne facultative n'existe que si son intitulé la nomme —
     la deviner ferait passer une colonne quelconque pour un numéro. */
  var OPTIONNELLES = [
    {
      cle: "telephone",
      mots: ["telephone", "tel.", "phone", "mobile", "whatsapp", "contact"],
    },
    { cle: "adresse", mots: ["adresse", "address", "quartier", "rue", "lot "] },
    { cle: "horaires", mots: ["horaire", "ouverture", "ouvert", "heures", "hours"] },
    { cle: "site", mots: ["site", "web", "url", "facebook", "lien", "page"] },
  ];

  var CATEGORY_FIXES = {
    Supermaché: "Supermarché",
    Supermarche: "Supermarché",
    Epicerie: "Épicerie",
    Hotel: "Hôtel",
  };
  var PROVINCE_FIXES = {
    Antsirananana: "Antsiranana",
    Fianaratsoa: "Fianarantsoa",
  };
  var VIDE = "Non renseignée";

  /* ------------------------------ Utilitaires ---------------------------- */

  /* Minuscules sans accents : « Téléphone » et « telephone » se valent. Les
     mots-clés ci-dessus sont déjà écrits sans accent, d'où la comparaison. */
  function plier(texte) {
    return String(texte)
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  }

  /* Région administrative. Le Sheet ne la porte pas — sa colonne « Province »
     mélange villes et anciennes provinces — et le navigateur n'a ni les
     polygones ADM1 ni de quoi les parcourir. `build.py` fait le calcul au
     moment de l'instantané et y dépose la table ville → région, que les lignes
     relues en direct réutilisent. Une ville absente de la table — ajoutée au
     Sheet depuis le dernier passage du workflow horaire — laisse la région
     vide : la fiche reste dans le tableau, sous « Région à préciser ». */
  function regionDe(province) {
    var table = (global.EARIARY_PARTENAIRES || {}).regions_par_ville || {};
    return table[province] || "";
  }

  /* Analyseur CSV minimal mais correct sur les guillemets : les noms
     d'établissement contiennent des virgules et des guillemets français. */
  function parseCSV(text) {
    var rows = [];
    var row = [];
    var value = "";
    var quoted = false;

    for (var i = 0; i < text.length; i += 1) {
      var c = text[i];
      if (quoted) {
        if (c === '"') {
          if (text[i + 1] === '"') {
            value += '"';
            i += 1;
          } else {
            quoted = false;
          }
        } else {
          value += c;
        }
      } else if (c === '"') {
        quoted = true;
      } else if (c === ",") {
        row.push(value);
        value = "";
      } else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i += 1;
        row.push(value);
        rows.push(row);
        row = [];
        value = "";
      } else {
        value += c;
      }
    }
    row.push(value);
    rows.push(row);

    return rows
      .map(function (cells) {
        return cells.map(function (cell) {
          return cell.trim();
        });
      })
      .filter(function (cells) {
        return cells.some(function (cell) {
          return cell !== "";
        });
      });
  }

  /* Le Sheet commence parfois par un titre ou une ligne vide : la vraie
     en-tête est la première qui nomme une colonne connue. */
  function indexEnTete(rows) {
    for (var i = 0; i < Math.min(rows.length, 10); i += 1) {
      var ligne = plier(rows[i].join(" "));
      if (ligne.indexOf("province") !== -1 || ligne.indexOf("etablissement") !== -1) {
        return i;
      }
    }
    return 0;
  }

  /* `pris` évite qu'une colonne déjà attribuée soit reprise par un champ
     facultatif : la colonne des coordonnées n'est pas celle de l'adresse. */
  function indexColonne(entete, mots, defaut, pris) {
    for (var i = 0; i < entete.length; i += 1) {
      if (pris.indexOf(i) !== -1) continue;
      var bas = plier(entete[i]);
      for (var j = 0; j < mots.length; j += 1) {
        if (bas.indexOf(mots[j]) !== -1) return i;
      }
    }
    return defaut;
  }

  function parseCoords(brut) {
    var m = COORD_RE.exec(String(brut).replace(/\\/g, "").trim());
    if (!m) return [null, null];
    var lat = parseFloat(m[1].replace(",", "."));
    var lon = parseFloat(m[2].replace(",", "."));
    if (!(lat >= -90 && lat <= 90) || !(lon >= -180 && lon <= 180)) {
      return [null, null];
    }
    return [lat, lon];
  }

  function capitaliser(texte) {
    return texte ? texte.charAt(0).toUpperCase() + texte.slice(1).toLowerCase() : texte;
  }

  /* --------------------------- Mise en forme ----------------------------- */

  /* Renvoie `{ etablissements, champs }` — `champs` étant les colonnes
     facultatives réellement remplies. Une colonne présente mais entièrement
     vide ne compte pas : elle ferait apparaître une colonne « Contact » sans
     un seul numéro. */
  function normaliser(rows) {
    if (!rows.length) return { etablissements: [], champs: [] };
    var iEntete = indexEnTete(rows);
    var entete = rows[iEntete];

    var pris = [];
    var index = {};
    COLONNES.forEach(function (colonne) {
      var position = indexColonne(entete, colonne.mots, colonne.defaut, pris);
      index[colonne.cle] = position;
      if (position !== null) pris.push(position);
    });
    OPTIONNELLES.forEach(function (colonne) {
      var position = indexColonne(entete, colonne.mots, null, pris);
      index[colonne.cle] = position;
      if (position !== null) pris.push(position);
    });

    var out = [];
    for (var r = iEntete + 1; r < rows.length; r += 1) {
      var cells = rows[r];
      var lire = function (position) {
        if (position === null || position === undefined) return "";
        return position < cells.length ? cells[position] : "";
      };

      var nom = lire(index.nom);
      if (!nom || nom.toLowerCase() === "nan" || nom.toLowerCase() === "none") continue;

      var categorie = capitaliser(lire(index.categorie));
      categorie = CATEGORY_FIXES[categorie] || categorie || VIDE;
      var province = lire(index.province);
      province = PROVINCE_FIXES[province] || province || VIDE;
      var brut = lire(index.coordonnees);
      var coords = parseCoords(brut);

      var fiche = {
        nom: nom,
        categorie: categorie,
        province: province,
        region: regionDe(province),
        lat: coords[0],
        lon: coords[1],
        coordonnees_brutes: brut,
      };
      OPTIONNELLES.forEach(function (colonne) {
        var valeur = lire(index[colonne.cle]);
        if (valeur) fiche[colonne.cle] = valeur;
      });
      out.push(fiche);
    }

    var champs = OPTIONNELLES.map(function (colonne) {
      return colonne.cle;
    }).filter(function (cle) {
      return out.some(function (fiche) {
        return fiche[cle];
      });
    });

    return { etablissements: out, champs: champs };
  }

  /* Empreinte du jeu de données, pour ne redessiner que s'il a bougé : un
     rafraîchissement qui ne change rien ne doit pas défaire la sélection du
     visiteur ni recadrer sa carte. */
  function signature(etablissements) {
    return etablissements
      .map(function (e) {
        return [
          e.nom,
          e.categorie,
          e.province,
          e.lat,
          e.lon,
          e.telephone || "",
          e.adresse || "",
          e.horaires || "",
          e.site || "",
        ].join("");
      })
      .join("");
  }

  /* -------------------------------- Sources ------------------------------ */

  function instantane() {
    var snap = global.EARIARY_PARTENAIRES;
    if (!snap || !snap.etablissements || !snap.etablissements.length) return null;
    return {
      etablissements: snap.etablissements,
      champs: snap.champs || [],
      source: "instantane",
      genereLe: snap.genere_le || "",
    };
  }

  /* Relit le Sheet. Résout avec les données ou rejette — l'appelant décide.
     15 s : le premier appel à gviz demande régulièrement une dizaine de
     secondes. L'attente ne se voit pas, l'instantané étant déjà affiché. */
  function enDirect(timeoutMs) {
    var controle = typeof AbortController === "function" ? new AbortController() : null;
    var minuteur = global.setTimeout(function () {
      if (controle) controle.abort();
    }, timeoutMs || 15000);

    return fetch(SHEET_URL, {
      signal: controle ? controle.signal : undefined,
      cache: "no-store",
      credentials: "omit",
    })
      .then(function (reponse) {
        if (!reponse.ok) throw new Error("HTTP " + reponse.status);
        return reponse.text();
      })
      .then(function (texte) {
        var resultat = normaliser(parseCSV(texte));
        if (!resultat.etablissements.length) throw new Error("feuille vide");
        return {
          etablissements: resultat.etablissements,
          champs: resultat.champs,
          source: "direct",
          genereLe: "",
        };
      })
      .finally(function () {
        global.clearTimeout(minuteur);
      });
  }

  /* ---------------------------- Suivi du Sheet --------------------------- */

  /* Relit le Sheet à intervalle régulier et prévient l'appelant quand les
     données ont changé — c'est ce qui fait que le tableau et la carte se
     mettent à jour au fil du remplissage du Sheet, sans que personne n'ait à
     recharger la page.

     Rien ne tourne quand l'onglet est masqué : une iframe posée dans un onglet
     d'arrière-plan interrogerait Google indéfiniment pour rien. Au retour du
     visiteur, la relecture est immédiate si le dernier appel remonte à plus
     d'un intervalle — l'affichage est donc à jour dès qu'il regarde.

     `suivre` renvoie une fonction d'arrêt. */
  function suivre(reglages) {
    var options = reglages || {};
    var intervalle = Math.max(Number(options.intervalle) || 0, 0);
    var surDonnees = options.surDonnees || function () {};
    var surEchec = options.surEchec || function () {};
    var derniere = "";
    var dernierAppel = 0;
    var enCours = false;
    var minuteur = null;
    var arrete = false;

    function maintenant() {
      return Date.now();
    }

    function relire(premier) {
      if (arrete || enCours) return Promise.resolve();
      enCours = true;
      dernierAppel = maintenant();
      return enDirect(options.delai)
        .then(function (donnees) {
          var empreinte = signature(donnees.etablissements);
          // Premier appel : on remonte toujours les données, même identiques à
          // l'instantané — c'est ce qui fait passer la note de provenance de
          // « relevé du … » à « consulté à l'instant ».
          if (premier || empreinte !== derniere) {
            derniere = empreinte;
            surDonnees(donnees, { premier: Boolean(premier) });
          }
        })
        .catch(function (erreur) {
          surEchec(erreur, { premier: Boolean(premier) });
        })
        .finally(function () {
          enCours = false;
        });
    }

    function planifier() {
      if (!intervalle || arrete) return;
      minuteur = global.setInterval(function () {
        // `document.hidden` couvre l'onglet d'arrière-plan ; une iframe
        // simplement défilée hors de l'écran, elle, reste « visible » — c'est
        // le comportement voulu, le visiteur peut y revenir d'un coup de
        // molette.
        if (global.document.hidden) return;
        relire(false);
      }, intervalle);

      global.document.addEventListener("visibilitychange", function () {
        if (arrete || global.document.hidden) return;
        if (maintenant() - dernierAppel >= intervalle) relire(false);
      });
    }

    var initial = relire(true).then(planifier);

    return {
      initial: initial,
      relire: function () {
        return relire(false);
      },
      arreter: function () {
        arrete = true;
        if (minuteur) global.clearInterval(minuteur);
      },
    };
  }

  global.EARIARY_DONNEES = {
    instantane: instantane,
    enDirect: enDirect,
    suivre: suivre,
    signature: signature,
    parseCSV: parseCSV,
    normaliser: normaliser,
    regionDe: regionDe,
    plier: plier,
  };
})(window);
