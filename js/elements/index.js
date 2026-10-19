// @slowboard/elements: the app sheet as custom elements, shared by slowboard.io and the hub.
//
//   <script type="module" src="slowboard-elements.js"></script>
//   <slowapp-sheet base="/catalog/weather/">
//     <script type="application/json">{"catalog": 1, "app": {…}, …}</script>
//   </slowapp-sheet>
//
// or `el.catalog = bundle` from a script. Framework-free; shadow DOM with a constructed stylesheet,
// no inline script or style, no eval, no network of its own (only the <img>s the host points at),
// so it runs under a hub's `default-src 'self'` CSP. Importing the module in Node (a site's build)
// defines nothing and is safe: use the render functions there.

import { css } from "./styles.js";
import { renderDisk, renderFacts, renderGrants, renderScreens, renderSheet, sheetModel } from "./render.js";

export { css } from "./styles.js";
export * from "./render.js";
export const VERSION = "0.1.0";

const HTMLElementBase = globalThis.HTMLElement ?? class {};
let shared = null;
/** The one constructed stylesheet every element adopts (null where there's no CSSOM). */
export function stylesheet() {
  if (!shared && typeof CSSStyleSheet === "function" && "replaceSync" in CSSStyleSheet.prototype) {
    shared = new CSSStyleSheet();
    shared.replaceSync(css);
  }
  return shared;
}

// The hub's exact maps from the panel's inks to the site's (and, in the dark, black and white
// swapped); used with the ink-filter attribute.
const FILTERS = `<svg class="filters" width="0" height="0" aria-hidden="true" focusable="false">`
  + `<filter id="slowapp-ink-light" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="0.81569 0.11765 0.00000 0 0.06667  -0.04314 0.84706 0.12941 0 0.06667  -0.06667 0.00000 1.00000 0 0.06667  0 0 0 1 0"/></filter>`
  + `<filter id="slowapp-ink-dark" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="-0.06275 0.11765 -0.92157 0 0.94510  -0.91765 0.84706 -0.79216 0 0.94118  -0.92549 0.00000 0.07843 0 0.92549  0 0 0 1 0"/></filter></svg>`;

const DATA_KEYS = ["catalog", "cards", "touches", "links", "crumb", "note"];

/**
 * The shared base: data from properties, or from a child <script type="application/json">
 * (a bundle, or {catalog, cards, touches, links, crumb, note}); attributes base, no, theme,
 * ink-filter. Renders into an open shadow root, adopting a server-rendered one if it's there.
 */
class SlowappElement extends HTMLElementBase {
  static get observedAttributes() { return ["base", "no", "theme", "ink-filter", "nohead"]; }

  constructor() {
    super();
    this._data = {};
    this._ready = false;
  }

  connectedCallback() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const sheet = stylesheet();
    if (sheet) this.shadowRoot.adoptedStyleSheets = [sheet];
    if (!this._fromProps) this._readJson();
    this._ready = true;
    this.render();
  }

  attributeChangedCallback() { if (this._ready) this.render(); }

  _readJson() {
    const s = [...this.children].find((c) => c.localName === "script" && c.type === "application/json");
    if (!s) return;
    try {
      const v = JSON.parse(s.textContent || "{}");
      this._data = v && v.catalog === 1 ? { catalog: v } : (v || {});
    } catch (e) {
      this._data = {};
      console.warn(`<${this.localName}>: its JSON doesn't parse (${e.message})`);
    }
  }

  /** The input sheetModel() takes, from the properties, the JSON and the attributes. */
  get input() {
    return { ...this._data, base: this.getAttribute("base") ?? this._data.base ?? "", no: this.getAttribute("no") ?? this._data.no ?? "" };
  }

  get model() { return sheetModel(this.input); }

  /** True once there's something to show: a catalog or cards, from properties or the JSON. */
  get hasData() { return !!(this._data.catalog || this._data.cards); }

  render() {
    if (!this.shadowRoot) return;
    const m = this.model;
    // Server-rendered with no data to re-render from: keep that markup, and make it work.
    if (!this.hasData && this.shadowRoot.querySelector("link[rel=stylesheet], section, div")) {
      this.wire(m);
      return;
    }
    this.shadowRoot.innerHTML = this.html(m) + (this.hasAttribute("ink-filter") ? FILTERS : "");
    this.wire(m);
  }

  html() { return ""; }
  wire() {}
}
for (const k of DATA_KEYS) {
  Object.defineProperty(SlowappElement.prototype, k, {
    get() { return this._data[k]; },
    set(v) { this._data = { ...this._data, [k]: v }; this._fromProps = true; if (this._ready) this.render(); },
  });
}

const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The screens' behaviour inside a shadow root: the size picker and the e-paper "Next card". */
function wireScreens(el, root, m) {
  const decks = [...root.querySelectorAll("[data-deck]")];
  for (const d of decks) {
    const epd = d.querySelector("[data-epd]");
    // The frame takes the size's shape (CSSOM, which CSP allows; the CSS default is 452/480).
    if (epd && d.dataset.w && d.dataset.h) epd.style.aspectRatio = `${d.dataset.w} / ${d.dataset.h}`;
    const b = d.querySelector("[data-tap]");
    if (!b || !epd) continue;
    b.addEventListener("click", () => {
      const cards = [...epd.querySelectorAll("[data-card]")];
      const at = cards.findIndex((c) => !c.hidden);
      const next = (at + 1) % cards.length;
      const swap = () => {
        cards.forEach((c, i) => (c.hidden = i !== next));
        el.dispatchEvent(new CustomEvent("slowapp-card", { bubbles: true, composed: true,
          detail: { deck: +d.dataset.deck, index: next, src: cards[next].getAttribute("src") } }));
      };
      if (reduced()) return swap();
      b.disabled = true;
      epd.dataset.refresh = "black";
      setTimeout(() => { epd.dataset.refresh = "white"; }, 160);
      setTimeout(() => { swap(); epd.dataset.refresh = "ink"; }, 320);
      setTimeout(() => { delete epd.dataset.refresh; b.disabled = false; }, 1210);
    });
  }
  for (const b of root.querySelectorAll("[data-size]")) {
    b.addEventListener("click", () => {
      const i = +b.dataset.size;
      decks.forEach((d) => (d.hidden = +d.dataset.deck !== i));
      root.querySelectorAll("[data-size]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      el.dispatchEvent(new CustomEvent("slowapp-size", { bubbles: true, composed: true, detail: { index: i, size: m.decks[i]?.id } }));
    });
  }
}

/** The whole app sheet: head (disk, title, author), screens, what it may touch, details, links. */
export class SlowappSheet extends SlowappElement {
  html(m) { return renderSheet(m, { head: !this.hasAttribute("nohead") }); }
  wire(m) { wireScreens(this, this.shadowRoot, m); }
}

/** Only the screens: a deck per size with the size picker and "Next card". */
export class SlowappScreens extends SlowappElement {
  html(m) { return `<div class="cards" data-screens part="screens">${renderScreens(m)}</div>`; }
  wire(m) { wireScreens(this, this.shadowRoot, m); }
}

/** Only what it may touch (and the other grants). */
export class SlowappGrants extends SlowappElement {
  html(m) { return `<div class="about">${renderGrants(m)}</div>`; }
}

/** Only the details: version, licence, feeds with sizes and inks, download sizes. */
export class SlowappFacts extends SlowappElement {
  html(m) { return renderFacts(m); }
}

/** The disk alone: attributes no, ink, name, size (tile | feature), or the catalog's app. */
export class SlowappDisk extends SlowappElement {
  static get observedAttributes() { return [...super.observedAttributes, "ink", "name", "size"]; }
  get hasData() { return super.hasData || this.hasAttribute("name"); }
  html(m) {
    return renderDisk({ no: m.no, title: this.getAttribute("name") ?? m.title, ink: this.getAttribute("ink") ?? m.ink,
      size: this.getAttribute("size") ?? "tile" });
  }
}

export const ELEMENTS = {
  "slowapp-sheet": SlowappSheet,
  "slowapp-screens": SlowappScreens,
  "slowapp-grants": SlowappGrants,
  "slowapp-facts": SlowappFacts,
  "slowapp-disk": SlowappDisk,
};

/** Registers the elements (idempotent). Called on import wherever customElements exists. */
export function define(registry = globalThis.customElements) {
  if (!registry) return;
  for (const [tag, cls] of Object.entries(ELEMENTS)) if (!registry.get(tag)) registry.define(tag, cls);
}

define();
