/* Accès aux données du registre des partenaires.
 *
 * Expose window.EARIARY_DONNEES, utilisé par carte.js et tableau.js.
 *
 * Deux sources :
 *   1. window.EARIARY_PARTENAIRES — l'instantané embarqué (assets/instantane.js),
 *      affiché immédiatement, sans attendre le réseau ;
 *   2. le Google Sheet, relu en direct, qui remplace l'instantané dès qu'il
 *      répond puis à intervalle régulier (voir `suivre`).
 *
 * Les règles de lecture reproduisent celles de partenaires/build.py. Toute
 * modification ici doit être reportée là-bas, et inversement.
 *
 * Écrit en ES5 (var, pas de classes) : ces pages sont intégrées dans des
 * applications tierces dont on ne maîtrise pas le parc de navigateurs.
 */

(function (global) {
  "use strict";

  var SHEET_ID = "1D15egjrBB_9eNCXC-THxZcSqvNtf7ttfssdcVDRu8Yo";
  var GID = "0";

  // Endpoint « gviz » et non « /export » : lui seul renvoie les en-têtes CORS
  // permettant un fetch() depuis une autre origine.
  var SHEET_URL =
    "https://docs.google.com/spreadsheets/d/" +
    SHEET_ID +
    "/gviz/tq?tqx=out:csv&gid=" +
    GID;

  // Format accepté : « -12.289942, 49.291381 ».
  var COORD_RE = /^\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*[,;]\s*\\?\s*(-?\d{1,3}[.,]\d+)\s*$/;

  // Colonnes obligatoires : mots-clés cherchés dans l'en-tête, et position de
  // repli utilisée si aucun mot-clé ne correspond.
  var COLONNES = [
    { cle: "province", mots: ["province", "ville", "region"], defaut: 0 },
    { cle: "nom", mots: ["etablissement", "enseigne", "nom"], defaut: 1 },
    { cle: "categorie", mots: ["categorie", "type"], defaut: 2 },
    { cle: "coordonnees", mots: ["latitude", "longitude", "coord", "gps"], defaut: 3 },
  ];

  // Colonnes facultatives : reconnues uniquement par leur intitulé, jamais par
  // leur position. Mots-clés écrits sans accent (voir `plier`).
  var OPTIONNELLES = [
    {
      cle: "telephone",
      mots: ["telephone", "tel.", "phone", "mobile", "whatsapp", "contact"],
    },
    { cle: "adresse", mots: ["adresse", "address", "quartier", "rue"] },
    { cle: "horaires", mots: ["horaire", "ouverture", "ouvert", "heures", "hours"] },
    { cle: "site", mots: ["site", "web", "url", "facebook", "lien", "page"] },
  ];

  // Fautes de frappe présentes dans le Sheet. À supprimer d'ici ET de
  // partenaires/build.py une fois le Sheet corrigé.
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

  // Délai maximal d'un appel au Sheet. Le premier peut demander une dizaine de
  // secondes ; l'attente ne se voit pas, l'instantané étant déjà affiché.
  var DELAI_MS = 15000;

  /* ------------------------------ Utilitaires ---------------------------- */

  /** Minuscules sans accents. Sert aux comparaisons d'intitulés et de recherche. */
  function plier(texte) {
    return String(texte)
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  }

  /**
   * Région d'une ville, d'après la table déposée dans l'instantané par
   * build.py. Le navigateur n'a pas les polygones administratifs.
   * Retourne "" pour une ville ajoutée au Sheet depuis la dernière génération.
   */
  function regionDe(province) {
    var table = (global.EARIARY_PARTENAIRES || {}).regions_par_ville || {};
    return table[province] || "";
  }

  /**
   * Analyseur CSV. Gère les guillemets et les guillemets doublés : les noms
   * d'établissement contiennent des virgules et des guillemets.
   * Retourne un tableau de lignes, chaque ligne étant un tableau de cellules.
   */
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
            value += '"'; // guillemet échappé
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
        if (c === "\r" && text[i + 1] === "\n") i += 1; // fin de ligne Windows
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

  /** Indice de la ligne d'en-tête : la première contenant un intitulé connu. */
  function indexEnTete(rows) {
    for (var i = 0; i < Math.min(rows.length, 10); i += 1) {
      var ligne = plier(rows[i].join(" "));
      if (ligne.indexOf("province") !== -1 || ligne.indexOf("etablissement") !== -1) {
        return i;
      }
    }
    return 0;
  }

  /**
   * Indice de la première colonne libre dont l'intitulé contient un mot-clé.
   * `pris` liste les colonnes déjà attribuées.
   */
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

  /** [latitude, longitude], ou [null, null] si la cellule est inexploitable. */
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

  /** Première lettre en majuscule, le reste en minuscules. */
  function capitaliser(texte) {
    return texte ? texte.charAt(0).toUpperCase() + texte.slice(1).toLowerCase() : texte;
  }

  /* --------------------------- Mise en forme ----------------------------- */

  /**
   * Transforme les lignes CSV en fiches.
   * Retourne { etablissements, champs }, `champs` listant les colonnes
   * facultatives réellement remplies (une colonne vide n'y figure pas).
   */
  function normaliser(rows) {
    if (!rows.length) return { etablissements: [], champs: [] };
    var iEntete = indexEnTete(rows);
    var entete = rows[iEntete];

    // Obligatoires d'abord, facultatives ensuite sur les colonnes restantes.
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

    function lireCellule(cells, position) {
      if (position === null || position === undefined) return "";
      return position < cells.length ? cells[position] : "";
    }

    var out = [];
    for (var r = iEntete + 1; r < rows.length; r += 1) {
      var cells = rows[r];
      var nom = lireCellule(cells, index.nom);
      if (!nom || nom.toLowerCase() === "nan" || nom.toLowerCase() === "none") continue;

      var categorie = capitaliser(lireCellule(cells, index.categorie));
      categorie = CATEGORY_FIXES[categorie] || categorie || VIDE;
      var province = lireCellule(cells, index.province);
      province = PROVINCE_FIXES[province] || province || VIDE;
      var brut = lireCellule(cells, index.coordonnees);
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
      // Champ facultatif vide = champ absent de la fiche.
      OPTIONNELLES.forEach(function (colonne) {
        var valeur = lireCellule(cells, index[colonne.cle]);
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

  /**
   * Empreinte du jeu de données, pour détecter un changement réel.
   * Sans elle, chaque relecture redessinerait la page inutilement.
   */
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
        ].join("");
      })
      .join("");
  }

  /* -------------------------------- Sources ------------------------------ */

  /** Données de l'instantané embarqué, ou null s'il est absent ou vide. */
  function instantane() {
    var snap = global.EARIARY_PARTENAIRES;
    if (!snap || !snap.etablissements || !snap.etablissements.length) return null;
    return {
      etablissements: snap.etablissements,
      champs: snap.champs || [],
      source: "instantane",
    };
  }

  /**
   * Relit le Google Sheet.
   * Retourne une promesse résolue avec { etablissements, champs, source },
   * ou rejetée (réseau, feuille privée, feuille vide) : c'est à l'appelant de
   * décider quoi faire de l'échec.
   */
  function enDirect(timeoutMs) {
    var controle = typeof AbortController === "function" ? new AbortController() : null;
    var minuteur = global.setTimeout(function () {
      if (controle) controle.abort();
    }, timeoutMs || DELAI_MS);

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
        };
      })
      .finally(function () {
        global.clearTimeout(minuteur);
      });
  }

  /* ---------------------------- Suivi du Sheet --------------------------- */

  /**
   * Relit le Sheet immédiatement, puis toutes les `intervalle` millisecondes,
   * et appelle `surDonnees` uniquement quand les données ont changé. C'est ce
   * qui met la page à jour au fil du remplissage du Sheet.
   *
   * Rien n'est appelé quand l'onglet est masqué. Au retour du visiteur, une
   * relecture est déclenchée si le dernier appel date de plus d'un intervalle.
   *
   * Options :
   *   intervalle  période en ms ; 0 pour ne relire qu'une fois
   *   delai       délai maximal d'un appel, en ms (défaut : DELAI_MS)
   *   surDonnees  fonction (donnees, { premier })
   *   surEchec    fonction (erreur, { premier })
   *
   * Retourne { initial, relire, arreter }.
   */
  function suivre(reglages) {
    var options = reglages || {};
    var intervalle = Math.max(Number(options.intervalle) || 0, 0);
    var surDonnees = options.surDonnees || function () {};
    var surEchec = options.surEchec || function () {};
    var derniere = ""; // empreinte du dernier jeu de données remonté
    var dernierAppel = 0;
    var enCours = false;
    var minuteur = null;
    var arrete = false;

    function relire(premier) {
      if (arrete || enCours) return Promise.resolve();
      enCours = true;
      dernierAppel = Date.now();
      return enDirect(options.delai)
        .then(function (donnees) {
          var empreinte = signature(donnees.etablissements);
          // Le premier appel remonte toujours les données, même identiques à
          // l'instantané : l'appelant doit savoir que la source est en direct.
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
        if (global.document.hidden) return;
        relire(false);
      }, intervalle);

      global.document.addEventListener("visibilitychange", function () {
        if (arrete || global.document.hidden) return;
        if (Date.now() - dernierAppel >= intervalle) relire(false);
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
