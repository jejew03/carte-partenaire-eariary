/* Lecture des données de l'iframe.
 *
 * Deux sources, dans cet ordre :
 *   1. `window.EARIARY_SNAPSHOT` — instantané versionné (assets/etablissements.js),
 *      affiché tout de suite, sans attendre le réseau ;
 *   2. le Google Sheet, relu dans le navigateur, qui remplace l'instantané dès
 *      qu'il répond. Un échec (Sheet privé, hors ligne, CSP de l'application
 *      hôte) est silencieux : la pastille de la barre de titre reste sur
 *      « instantané ».
 *
 * Les règles de nettoyage reproduisent celles de `embed/build.py` et de
 * `load_data()` dans `app.py` — même détection d'en-tête, mêmes mots-clés de
 * colonnes, mêmes corrections de libellés.
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

  /* Région administrative. Le Sheet ne la porte pas — sa colonne « Province »
     mélange villes et anciennes provinces — et le navigateur n'a pas les
     polygones ADM1 pour la déduire des coordonnées. `build.py` le fait au
     moment de l'instantané et y dépose la table ville → région, que les lignes
     relues en direct réutilisent. Une ville absente de la table (ajoutée au
     Sheet depuis le dernier `build.py`) laisse la région vide : la fiche reste
     dans le tableau, sous « Région à préciser ». */
  function regionDe(province) {
    var table = (global.EARIARY_SNAPSHOT || {}).regions_par_ville || {};
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

  function indexEnTete(rows) {
    for (var i = 0; i < Math.min(rows.length, 10); i += 1) {
      if (rows[i].join(" ").toLowerCase().indexOf("province") !== -1) return i;
    }
    return 0;
  }

  function indexColonne(entete, motsCles, defaut) {
    for (var i = 0; i < entete.length; i += 1) {
      var bas = entete[i].toLowerCase();
      for (var j = 0; j < motsCles.length; j += 1) {
        if (bas.indexOf(motsCles[j]) !== -1) return i;
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

  function normaliser(rows) {
    if (!rows.length) return [];
    var iEntete = indexEnTete(rows);
    var entete = rows[iEntete];

    var iProv = indexColonne(entete, ["province", "région", "region"], 0);
    var iNom = indexColonne(entete, ["établissement", "etablissement", "nom"], 1);
    var iCat = indexColonne(entete, ["catégorie", "categorie", "type"], 2);
    var iGeo = indexColonne(entete, ["latitude", "longitude", "coord", "gps"], 3);

    var out = [];
    for (var r = iEntete + 1; r < rows.length; r += 1) {
      var cells = rows[r];
      var lire = function (index) {
        return index < cells.length ? cells[index] : "";
      };

      var nom = lire(iNom);
      if (!nom || nom.toLowerCase() === "nan" || nom.toLowerCase() === "none") continue;

      var categorie = capitaliser(lire(iCat));
      categorie = CATEGORY_FIXES[categorie] || categorie || VIDE;
      var province = lire(iProv);
      province = PROVINCE_FIXES[province] || province || VIDE;
      var brut = lire(iGeo);
      var coords = parseCoords(brut);

      out.push({
        nom: nom,
        categorie: categorie,
        province: province,
        region: regionDe(province),
        lat: coords[0],
        lon: coords[1],
        coordonnees_brutes: brut,
      });
    }
    return out;
  }

  function instantane() {
    var snap = global.EARIARY_SNAPSHOT;
    if (!snap || !snap.etablissements || !snap.etablissements.length) return null;
    return {
      etablissements: snap.etablissements,
      source: "instantane",
      genereLe: snap.genere_le || "",
    };
  }

  /* Relit le Sheet. Résout avec les données ou rejette — l'appelant décide.
     15 s : le premier appel à gviz demande régulièrement une dizaine de
     secondes (mesuré à 12 s à froid, 4 s ensuite). L'attente ne se voit pas,
     l'instantané étant déjà affiché. */
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
        var etablissements = normaliser(parseCSV(texte));
        if (!etablissements.length) throw new Error("feuille vide");
        return { etablissements: etablissements, source: "direct", genereLe: "" };
      })
      .finally(function () {
        global.clearTimeout(minuteur);
      });
  }

  global.EARIARY_DATA = {
    instantane: instantane,
    enDirect: enDirect,
    parseCSV: parseCSV,
    normaliser: normaliser,
    regionDe: regionDe,
  };
})(window);
