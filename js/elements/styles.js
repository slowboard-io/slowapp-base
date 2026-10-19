// The elements' stylesheet: slowboard.io's app page, inside a shadow root. The host provides the
// tokens (tokens.css: the four inks, the roles, the four fonts) as CSS custom properties, which
// inherit into the shadow root; the fallbacks here are tokens.css's own values. Light and dark
// come from the host's roles (--paper, --text, --keyline, --mark, --muted). Sizes follow the
// element's own width (a container), so the sheet fits a hub's column as well as a full page.
//
// Used as a constructed stylesheet (adoptedStyleSheets), which a strict CSP allows, and written
// out as elements.css by the build for a server-rendered <link>.

export const css = String.raw`
:host {
  --_black: var(--ink-black, #111111); --_white: var(--ink-white, #ffffff);
  --_yellow: var(--ink-yellow, #ffde00); --_red: var(--ink-red, #e10600);
  --_paper: var(--paper, var(--_white)); --_text: var(--text, var(--_black));
  --_keyline: var(--keyline, var(--_black)); --_mark: var(--mark, var(--_yellow)); --_muted: var(--muted, #4a4a4a);
  --_display: var(--font-display, "Press Start 2P", "Courier New", monospace);
  --_button: var(--font-button, "Silkscreen", "Courier New", monospace);
  --_code: var(--font-code, "VT323", ui-monospace, "SF Mono", Menlo, monospace);
  --_line: var(--line, 3px);
  --_gutter: var(--slowapp-gutter, max(16px, 4vw));
  --_band: var(--slowapp-band, 112px);
  --_ease: var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1));
  display: block; container: slowapp / inline-size; color: var(--_text);
}
:host([hidden]) { display: none; }
*, *::before, *::after { box-sizing: border-box; }
[hidden] { display: none !important; }
h1, h2, h3 { margin: 0; text-wrap: balance; }
p { margin: 0; text-wrap: pretty; }
img { max-width: 100%; display: block; }
a { color: inherit; text-decoration-thickness: 2px; text-underline-offset: 0.18em; }
a:hover { text-decoration-color: var(--_red); }
:focus-visible { outline: var(--_line) solid var(--_keyline); outline-offset: 3px; box-shadow: 0 0 0 calc(var(--_line) + 3px) var(--_mark); }
::selection { background: var(--_yellow); color: var(--_black); }

/* type */
.h2 { font: 700 clamp(1.25rem, 0.95rem + 1.2vw, 2rem)/1.25 var(--_display); text-transform: uppercase; }
.h3 { font: 700 clamp(0.9rem, 0.8rem + 0.35vw, 1.1rem)/1.35 var(--_display); text-transform: uppercase; }
.lede { font-size: var(--step-1, clamp(1.25rem, 1.15rem + 0.45vw, 1.5rem)); line-height: 1.45; max-width: 52ch; }
.note { font: 400 1.3rem/1.3 var(--_code); margin-top: 24px; }
.crumb { font: 400 1.35rem/1 var(--_code); }
.crumb a { text-decoration: none; }
.crumb a::before { content: "‹ "; }

/* buttons */
.btn {
  --bg: var(--_paper); --fg: var(--_text);
  display: inline-flex; align-items: center; gap: 8px; justify-content: center;
  min-height: 48px; padding: 12px 20px;
  font: 400 0.9rem/1.2 var(--_button); letter-spacing: 0.02em; text-transform: uppercase; text-decoration: none; text-align: center;
  color: var(--fg); background: var(--bg);
  border: var(--_line) solid var(--_keyline); border-bottom-width: 7px; border-radius: 0;
  cursor: pointer; transition: transform 120ms var(--_ease);
}
.btn:hover { --bg: var(--_yellow); --fg: var(--_black); }
.btn--yellow:hover { --bg: var(--_white); }
.btn:active { transform: translateY(4px); border-bottom-width: 3px; }
.btn:disabled { cursor: not-allowed; opacity: 0.55; transform: none; }
.btn--red { --bg: var(--_red); --fg: var(--_white); }
.btn--black { --bg: var(--_black); --fg: var(--_white); }
.btn--yellow { --bg: var(--_yellow); --fg: var(--_black); }
.btn--small { min-height: 44px; padding: 8px 14px; font-size: 0.82rem; }
.btn[aria-pressed="true"] { --bg: var(--solid, var(--_black)); --fg: var(--on-solid, var(--_white)); }
.actions { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 32px; }

/* the yellow diamond key */
.keyglyph__cap { fill: var(--_yellow); stroke: var(--_black); }
.keyglyph__legend { fill: var(--_black); }

/* the disk (= a slowapp) */
.disk {
  --body: var(--_white); --fg: var(--_black); --kl: var(--_line);
  position: relative; display: block; width: 100%; aspect-ratio: 90 / 94;
  container-type: inline-size; text-decoration: none; color: var(--_black);
  background: var(--_black);
  clip-path: polygon(0 0, 88% 0, 100% 12%, 100% 100%, 0 100%);
}
.disk__shell::before {
  content: ""; position: absolute; inset: var(--kl); background: var(--body);
  clip-path: polygon(0 0, calc(88% - 1px) 0, 100% calc(12% + 1px), 100% 100%, 0 100%);
}
.disk__shutter { position: absolute; top: 0; left: 25%; width: 50%; height: 26%; background: var(--fg); }
.disk__window { position: absolute; top: 4%; left: 58%; width: 14%; height: 18%; background: var(--body); }
.disk__label {
  position: absolute; left: 8%; right: 8%; top: 40%; bottom: 10%;
  display: flex; flex-direction: column; gap: 4cqi; padding: 6cqi 7cqi;
  background: var(--_white); border: var(--kl) solid var(--_black);
}
.disk__no { font: 400 11cqi/0.9 var(--_code); letter-spacing: 0.02em; }
.disk__title { font: 700 6.4cqi/1.3 var(--_display); text-transform: uppercase; overflow-wrap: normal; word-break: normal; }
.disk--yellow { --body: var(--_yellow); }
.disk--red { --body: var(--_red); }
.disk--black { --body: var(--_black); --fg: var(--_white); --kl: 0px; }
.disk--black .disk__label { border: 0; }
.disk--feature { max-width: 320px; filter: drop-shadow(6px 6px 0 var(--_black)); }

/* the head: the disk half in the drive */
.head { --dw: min(300px, 38vw); position: relative; padding: 32px var(--_gutter) 0; border-bottom: var(--_line) solid var(--_keyline); }
.head__crumb { margin-bottom: 32px; }
.head__disk { position: relative; z-index: 1; width: var(--dw); }
.head__bar {
  position: relative; z-index: 2;
  margin: calc(var(--dw) * -0.3) calc(-1 * var(--_gutter)) 0;
  min-height: calc(var(--dw) * 0.3 + 48px);
  padding: 32px var(--_gutter) 32px calc(var(--_gutter) + var(--dw) + 48px);
  display: grid; gap: 8px; align-content: center;
  background: var(--slowapp-bar, var(--_black)); color: var(--_white);
}
.head__bar::before { /* the drive's slot */
  content: ""; position: absolute; top: 0; left: calc(var(--_gutter) - 10px); width: calc(var(--dw) + 20px); height: 6px; background: #444;
}
.head__bar p { font: 400 1.4rem/1 var(--_code); color: var(--_yellow); }

/* the body: the screens beside the words */
.body {
  padding: var(--_band) var(--_gutter); border-bottom: var(--_line) solid var(--_keyline);
  display: grid; grid-template-columns: minmax(0, 340px) minmax(0, 1fr); gap: 72px; align-items: start;
}
.body--words { grid-template-columns: minmax(0, 1fr); }
.cards { display: grid; gap: 16px; justify-items: start; min-width: 0; }
.deck { display: grid; gap: 16px; justify-items: start; justify-self: stretch; }
.about { display: grid; gap: 24px; justify-items: start; min-width: 0; }
.about .h3 { margin-top: 24px; }
.about > .h3:first-child { margin-top: 0; }
:host([nohead]) .body { padding-top: 0; }
.sizes { display: flex; flex-wrap: wrap; gap: 8px; }

/* e-paper refresh: black, white, then ink settles */
.epd { position: relative; width: 100%; max-width: 340px; aspect-ratio: 452 / 480; background: var(--_white); border: var(--_line) solid var(--_keyline); overflow: hidden; }
.deck--wide .epd { max-width: none; }
.epd img { width: 100%; height: 100%; object-fit: cover; image-rendering: pixelated; }
.epd img[hidden] { display: none; }
.epd__flash { position: absolute; inset: 0; pointer-events: none; opacity: 0; }
[data-refresh="black"] > .epd__flash { opacity: 1; background: var(--_black); }
[data-refresh="white"] > .epd__flash { opacity: 1; background: var(--_white); }
[data-refresh="ink"] > img:not([hidden]) { animation: ink-in 880ms steps(4, end) both; }
@keyframes ink-in { from { filter: contrast(0.2) brightness(1.6); } to { filter: none; } }

/* the panel's own inks mapped to the host's, light and dark (the hub's preview filters) */
:host([ink-filter]) .epd img { filter: url(#slowapp-ink-light); }
@media (prefers-color-scheme: dark) { :host([ink-filter]:not([theme="light"])) .epd img { filter: url(#slowapp-ink-dark); } }
:host([ink-filter][theme="dark"]) .epd img { filter: url(#slowapp-ink-dark); }
.filters { position: absolute; width: 0; height: 0; overflow: hidden; }

/* what it may touch */
.touches { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0; border: var(--_line) solid var(--_keyline); width: 100%; max-width: 640px; }
.touches div { padding: 12px 14px; border-right: var(--_line) solid var(--_keyline); }
.touches div:last-child { border-right: 0; }
.touches dt { font: 700 0.68rem/1.6 var(--_display); text-transform: uppercase; }
.touches dd { margin: 8px 0 0; font: 400 1.45rem/1.05 var(--_code); }
.also { margin: 0; padding-left: 1.2em; display: grid; gap: 4px; max-width: 640px; }

/* the details */
.facts { margin: 0; display: grid; width: 100%; max-width: 640px; border-top: var(--_line) solid var(--_keyline); }
.facts div { display: grid; grid-template-columns: minmax(0, 11rem) minmax(0, 1fr); gap: 16px; padding: 10px 0; border-bottom: var(--_line) solid var(--_keyline); }
.facts dt { font: 700 0.68rem/1.6 var(--_display); text-transform: uppercase; padding-top: 4px; }
.facts dd { margin: 0; font: 400 1.35rem/1.1 var(--_code); overflow-wrap: anywhere; }
.sizelist { list-style: none; margin: 6px 0 0; padding: 0; display: grid; gap: 2px; }
.sizelist .no { color: var(--_muted); text-decoration: line-through; text-decoration-thickness: 1px; }
.inks { display: inline-flex; vertical-align: middle; margin-left: 8px; border: 2px solid var(--_keyline); }
.ink { display: block; width: 14px; height: 16px; }
.ink--black { background: var(--_black); } .ink--white { background: var(--_white); }
.ink--yellow { background: var(--_yellow); } .ink--red { background: var(--_red); }
.ink--grey { background: linear-gradient(90deg, #444, #bbb); }

@container slowapp (max-width: 1080px) {
  .body { grid-template-columns: minmax(0, 1fr); }
}
@container slowapp (max-width: 760px) {
  .body { padding-block: 72px; }
  .touches { grid-template-columns: minmax(0, 1fr); }
  .touches div { border-right: 0; border-bottom: var(--_line) solid var(--_keyline); }
  .touches div:last-child { border-bottom: 0; }
  .facts div { grid-template-columns: minmax(0, 1fr); gap: 4px; }
  .head { --dw: 140px; }
  .head__bar { padding-left: var(--_gutter); padding-top: calc(var(--dw) * 0.3 + 24px); }
}
@media (prefers-reduced-motion: reduce) {
  .btn { transition: none; }
}
`;
