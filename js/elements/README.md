# @slowboard/elements

A slowapp's sheet as custom elements, so slowboard.io's app pages and a hub's app pages are the
same thing: the disk in the drive, the screens at every size (with the e-paper "Next card"), what
the app may touch, its feeds, inks and download size. The input is the app's catalog bundle
(`catalog.json` from `slowapp catalog build`, MANIFEST.md "Catalog bundle"), or the part of it a
host has.

No framework and no dependencies. Shadow DOM with one constructed stylesheet (`adoptedStyleSheets`),
no inline script or style, no `eval`, no network of its own, so it runs under a hub's
`default-src 'self'` CSP.

```html
<script type="module" src="slowboard-elements.js"></script>

<slowapp-sheet base="/catalog/moon/" no="004">
  <script type="application/json">{"catalog": 1, "app": {…}, "grants": {…}, "screens": […], …}</script>
</slowapp-sheet>
```

```js
const el = document.querySelector("slowapp-sheet");
el.catalog = await (await fetch("/catalog/moon/catalog.json")).json();
```

## Elements

| Tag | Shows |
|---|---|
| `<slowapp-sheet>` | All of it: head (crumb, disk, title, `SLOW no · by author`), screens, about, grants, details, links |
| `<slowapp-screens>` | A deck per size, a size picker when there are several, "Next card" |
| `<slowapp-grants>` | What it may touch (internet, secrets, memory) and the other grants, one line each |
| `<slowapp-facts>` | Version, licence, each feed's sizes (unsupported ones with the reason) and inks, download per platform |
| `<slowapp-disk>` | The disk; attributes `name`, `ink`, `no`, `size` (`tile` or `feature`) |

**Data** (properties, or one child `<script type="application/json">` holding a bare bundle or an
object with these keys): `catalog` (the bundle; `app` alone is enough), `cards` (`[{src, alt,
synthetic}]`, a deck instead of the bundle's screens), `touches` (`{internet, secrets, memory}`,
words instead of the ones made from the grants), `links` (`[{href, label, tone}]`; default: the
repo), `crumb` (`{href, label}`), `note` (the line under the deck; default: the example's caption,
or "Demo card…" when a card is synthetic). Setting a property re-renders.

**Attributes**: `base` (the URL the bundle's `screens/…` paths are relative to), `no` (shelf
number), `nohead` (sheet without its head, for a page that has its own title), `ink-filter` (map
the panel's pure inks to the host's, and in the dark black and white swapped: the hub's preview
filters), `theme` (`light` | `dark`; default: the system's, used by `ink-filter`).

**Events** (bubble, composed): `slowapp-card` `{deck, index, src}` after "Next card";
`slowapp-size` `{index, size}` when a size is picked.

**Parts**: `head`, `disk`, `bar`, `body`, `screens`, `sizes`, `screen-frame`, `screen`, `about`,
`grants`, `also`, `facts`, `actions`, `button`.

**CSS custom properties** (inherited from the host; fallbacks are tokens.css's values): the inks
`--ink-black`, `--ink-white`, `--ink-yellow`, `--ink-red`; the roles `--paper`, `--text`,
`--keyline`, `--mark`, `--muted`, `--solid`, `--on-solid` (light and dark come from these); the
fonts `--font-display`, `--font-button`, `--font-code` (reading text inherits the host's `font`);
`--line`, `--step-1`, `--ease-out`; and the sheet's own `--slowapp-gutter` (side padding, default
`max(16px, 4vw)`), `--slowapp-band` (the body's top and bottom padding, default `112px`) and
`--slowapp-bar` (the head's bar, default `--ink-black`; a dark host may want it lighter than its
paper). The host loads the fonts (`@font-face` doesn't reach into a shadow root). Layout follows
the element's width (container queries at 1080 and 760 px).

## Server-rendered (slowboard.io)

The render functions have no DOM, so a site renders the same HTML at build time as Declarative
Shadow DOM, which shows before (and without) the script; the element re-renders from its JSON when
it upgrades:

```js
import { renderSheet, sheetModel, shadowTemplate } from "@slowboard/elements/dist/slowboard-elements.js";
const input = { catalog, base: "/catalog/moon/" };
const html = `<slowapp-sheet base="/catalog/moon/">${shadowTemplate(renderSheet(sheetModel(input)), { css: cssUrl })}`
  + `<script type="application/json">${JSON.stringify(input).replace(/</g, "\\u003c")}</script></slowapp-sheet>`;
```

`cssUrl` is wherever the host serves `dist/elements.css` (a `<link>` in the shadow root; the
element swaps it for its constructed stylesheet).

## Build

`npm run build` (here, or `npm run build` at the root) writes `dist/slowboard-elements.js` (one ES
module, not minified) and `dist/elements.css`. The module's first line is
`/*! @slowboard/elements <version> sha256:<hex> */`, the hash of the rest of the file, so a vendored
copy can be checked anywhere. The hub vendors it as `crates/slowhub/web/slowboard-elements.js`
(epaper-dashboard), slowboard.io as `vendor/slowboard-elements/`.

`demo/` is a page under the hub's CSP with the moon example's bundle (`test/moon`): serve `js/`
(`python3 -m http.server -d js`) and open `/elements/demo/` (`?theme=dark` for dark).
