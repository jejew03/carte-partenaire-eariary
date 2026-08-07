/* Catégories de marchands : couleur et glyphe.
 *
 * Partagé par les deux pages publiques — la carte (`index.html`) et le tableau
 * (`tableau.html`) — pour qu'un même type de commerce s'y lise de la même
 * façon. Une catégorie absente de la table prend le style neutre : le Sheet
 * peut en introduire une sans que la page ait à être touchée.
 *
 * Palette propre aux pages publiques : mêmes teintes de départ que
 * `CATEGORY_STYLE` (app.py), ramenées à une clarté et une saturation communes
 * pour former une série cohérente. Les couleurs vives d'origine viennent des
 * marqueurs par défaut de Leaflet ; elles se voient comme telles.
 *
 * Chaque catégorie a aussi son glyphe : la couleur ne porte jamais seule
 * l'information. Glyphes dessinés dans un carré de 13, en blanc.
 */

(function (global) {
  "use strict";

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

  global.EARIARY_CATEGORIES = {
    styles: CATEGORIES,
    defaut: DEFAUT,
    styleDe: function (categorie) {
      return CATEGORIES[categorie] || DEFAUT;
    },
  };
})(window);
