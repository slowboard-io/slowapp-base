// @slowboard/elements, the part with no DOM: a catalog bundle (MANIFEST.md "Catalog bundle") turned
// into the app sheet's view model, and that model into HTML. The elements render with these in the
// browser; a site renders the same HTML at build time (Declarative Shadow DOM), so the page looks
// the same before and after the script runs, and without it.
//
//   import { sheetModel, renderSheet } from "@slowboard/elements/render";
//   const html = renderSheet(sheetModel({ catalog, base: "/catalog/weather/" }));
//
// Everything that comes from the bundle is escaped, and links and image sources must be http(s)
// or relative. The HTML has no inline script or style (a hub's CSP has neither).

export const INKS = ["black", "white", "yellow", "red", "grey"];
const DISK_INKS = new Set(["black", "white", "yellow", "red"]);
const KINDS = ["home", "detail", "ask", "answer"];
const STANDARD = ["452x444.k4", "456x444.k4", "1360x444.k4"];
const INK_SET = { k4: ["black", "white", "yellow", "red"], g16: ["black", "grey", "white"] };

// ------------------------------------------------------------------ escaping

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

/** A URL that may go in href or src: http(s), protocol-relative excluded, or a relative path. */
export function safeUrl(u) {
  const s = String(u ?? "").trim();
  if (!s) return "";
  if (/^https?:\/\//i.test(s)) return s;
  if (s.startsWith("//")) return "";
  if (/^[a-z][a-z0-9+.-]*:/i.test(s)) return ""; // javascript:, data:, anything else with a scheme
  return s;
}

// ------------------------------------------------------------------ formatting

/** "256m" -> "256 MB", "1g" -> "1 GB", "512k" -> "512 KB". */
export function grantSize(s) {
  const m = /^(\d+)([kmg])$/i.exec(String(s ?? ""));
  return m ? `${m[1]} ${m[2].toUpperCase()}B` : String(s ?? "");
}

/** Bytes for people: 1234567 -> "1.2 MB". */
export function bytes(n) {
  if (typeof n !== "number" || !isFinite(n)) return "";
  if (n < 1000) return `${n} B`;
  const u = ["KB", "MB", "GB"];
  let v = n, i = -1;
  do { v /= 1000; i += 1; } while (v >= 1000 && i < u.length - 1);
  return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${u[i]}`;
}

/** "452x444.k4" -> {w: 452, h: 444, inks: "k4", label: "452×444"}. */
export function surface(s) {
  const m = /^(\d{1,4})x(\d{1,4})\.(k4|g16)$/.exec(String(s ?? ""));
  if (!m) return null;
  const w = +m[1], h = +m[2];
  return { id: s, w, h, inks: m[3], label: `${w}×${h}${m[3] === "g16" ? " grey" : ""}` };
}

const join = (xs) => xs.filter(Boolean).join(", ");

// ------------------------------------------------------------------ the model

/**
 * The sheet's view model. `input` is either a catalog bundle (`catalog.json`, `{catalog: 1, …}`)
 * or `{catalog, base, no, cards, touches, links, crumb, note}`:
 *   catalog  the bundle, or the part of it a host has (`app` alone is enough)
 *   base     the URL screen files are relative to (`screens/…` in the bundle), default ""
 *   no       the shelf number ("001"); shown on the disk
 *   cards    [{src, alt, synthetic}]: a deck to show instead of the bundle's screens
 *   touches  {internet, secrets, memory}: words to show instead of the ones made from the grants
 *   links    [{href, label, tone}] (tone "black" | "red" | "yellow" | "plain"); default: the repo
 *   crumb    {href, label}: a link above the disk (the site's "‹ Slowapps")
 *   titles   {appId: title}: other apps' titles, for the imports and exports lines
 *   note     a line under the deck; default: "Demo card, drawn in the app's style." when a card is
 *            synthetic, else the shown example's caption
 */
export function sheetModel(input = {}) {
  const opts = input && input.catalog === 1 ? { catalog: input } : (input || {});
  const cat = opts.catalog || {};
  const app = cat.app || {};
  const g = cat.grants || null;
  const base = opts.base ?? "";
  const src = (file) => safeUrl(base + file);
  const title = app.title || app.id || "Slowapp";

  // The decks: given cards, or the bundle's screens of its first good example, one per size.
  let decks = [];
  if (Array.isArray(opts.cards) && opts.cards.length) {
    decks = [{ id: "cards", label: "", w: 452, h: 480, cards: opts.cards.map((c) => ({
      src: safeUrl(c.src), alt: String(c.alt ?? ""), synthetic: !!c.synthetic,
      w: c.width ?? 452, h: c.height ?? 480 })) }];
  } else if (Array.isArray(cat.screens) && cat.screens.length) {
    decks = screenDecks(cat, title, src);
  }
  const shown = decks.length && decks[0].example ? (cat.examples || []).find((e) => e.name === decks[0].example) : null;

  const touches = opts.touches || (g ? {
    internet: g.network === "egress" ? "Yes, outgoing only" : "No",
    secrets: join([...(g.secrets || []), ...(g.optional_secrets || []).map((s) => `${s} (optional)`)]) || "None",
    memory: g.memory ? grantSize(g.memory) : "",
  } : null);

  const also = [];
  if (g) {
    // "calendar:agenda" -> "Calendar's agenda" when the host gives the app's title.
    const titles = opts.titles || {};
    const named = (x) => {
      const [a, n] = String(x).split(":");
      return titles[a] ? (n ? `${titles[a]}'s ${n}` : titles[a]) : String(x);
    };
    if (g.prompts) also.push("Asks you questions on the panel; you answer with a key on the board");
    if (g.ui) also.push("Has its own page in your hub");
    if (g.backend) also.push("Runs while its page is open");
    if (g.data_mb) also.push(`Keeps up to ${g.data_mb} MB of its own data`);
    if (g.imports?.length) also.push(`Reads ${join(g.imports.map(named))} from other apps`);
    if (g.exports?.length) also.push(`Shares ${join(g.exports.map(named))} with other apps`);
    if (g.events?.length) also.push(`Notices when ${join(g.events.map(named))}`);
  }

  const facts = [];
  const version = app.version || cat.release?.version;
  if (version) facts.push({ label: "Version", value: version });
  if (app.license) facts.push({ label: "Licence", value: app.license });
  for (const f of cat.feeds || []) facts.push({ label: feedLabel(f), value: feedLine(f), sizes: feedSizes(f), inks: feedInks(f) });
  // One download size, no platform names: amd64's, else the largest.
  const plats = cat.image?.platforms || {};
  const dl = Object.entries(plats).find(([k]) => k.endsWith("/amd64"))?.[1]
    ?? Object.values(plats).sort((a, b) => (b.download || 0) - (a.download || 0))[0];
  if (dl && typeof dl.download === "number") facts.push({ label: "Download", value: bytes(dl.download) });

  const links = Array.isArray(opts.links) ? opts.links
    : app.repo ? [{ href: app.repo, label: "Source on GitHub", tone: "black" }] : [];

  const synthetic = decks.some((d) => d.cards.some((c) => c.synthetic));
  return {
    id: app.id || "",
    title,
    no: opts.no ? String(opts.no) : "",
    author: app.author || "",
    version: version || "",
    ink: DISK_INKS.has(app.ink) ? app.ink : "white",
    about: app.about || app.blurb || "",
    crumb: opts.crumb && opts.crumb.href ? { href: safeUrl(opts.crumb.href), label: String(opts.crumb.label ?? "") } : null,
    decks,
    note: opts.note ?? (synthetic ? "Demo card, drawn in the app's style." : shown?.caption || ""),
    touches,
    also,
    facts,
    links: links.map((l) => ({ href: safeUrl(l.href), label: String(l.label ?? ""), tone: ["black", "red", "yellow"].includes(l.tone) ? l.tone : "" }))
      .filter((l) => l.href && l.label),
  };
}

function screenDecks(cat, title, src) {
  const examples = (cat.examples || []).filter((e) => !e.error);
  const ex = examples.find((e) => cat.screens.some((s) => s.example === e.name)) || null;
  if (!ex) return [];
  const mine = cat.screens.filter((s) => s.example === ex.name);
  const feedOrder = (cat.feeds || []).map((f) => f.name);
  const order = [...new Set([...STANDARD, ...mine.map((s) => s.surface)])];
  const decks = [];
  for (const sid of order) {
    const sf = surface(sid);
    const at = mine.filter((s) => s.surface === sid);
    if (!sf || !at.length) continue;
    at.sort((a, b) => (feedOrder.indexOf(a.feed) - feedOrder.indexOf(b.feed)) || (KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind)));
    decks.push({ id: sid, example: ex.name, label: sf.label, w: sf.w, h: sf.h, cards: at.map((s) => ({
      src: src(s.file), w: sf.w, h: sf.h, synthetic: false,
      alt: `${title}, ${s.kind === "ask" ? "question" : s.kind === "answer" ? "answer" : s.kind} card: ${s.title || s.card}` })) });
  }
  const frames = (ex.frames || []).filter((f) => f.file);
  if (frames.length) {
    decks.push({ id: "panel", example: ex.name, label: "Whole panel", w: 1360, h: 480, cards: frames.map((f) => ({
      src: src(f.file), w: 1360, h: 480, synthetic: false,
      alt: `${title} on the whole panel${f.kind === "prompt" ? ", asking" : ""}` })) });
  }
  return decks;
}

const cap = (s) => String(s).charAt(0).toUpperCase() + String(s).slice(1);

/** "Left card" for a slot feed, "Sleep picture" for a fixed-size one. */
function feedLabel(f) {
  return `${cap(f.name)} ${f.size === "slot" ? "card" : "picture"}`;
}

/** Where the feed goes: any third, or a fixed size after a noun ("the sleep band, 1284×340"). */
function feedLine(f) {
  if (f.size === "slot") return "any third of the panel";
  const dims = surface(`${f.size}.k4`)?.label || f.size;
  return f.name === "sleep" ? `the sleep band, ${dims}` : `a fixed picture, ${dims}`;
}

function feedSizes(f) {
  const out = [];
  for (const [sid, r] of Object.entries(f.surfaces || {})) {
    const sf = surface(sid);
    if (sf) out.push({ label: sf.label, ok: !!r.ok, error: r.error || "" });
  }
  return out;
}

function feedInks(f) {
  if (Array.isArray(f.inks) && f.inks.length) return INKS.filter((i) => f.inks.includes(i));
  const fromSets = (f.ink_sets || []).flatMap((s) => INK_SET[s] || []);
  return INKS.filter((i) => fromSets.includes(i));
}

// ------------------------------------------------------------------ HTML

/** The disk: a slowapp's mark. size: "feature" (the sheet's head) or "tile". */
export function renderDisk({ no = "", title = "", ink = "white", size = "feature", cls = "" } = {}) {
  const i = DISK_INKS.has(ink) ? ink : "white";
  return `<div class="disk disk--${size === "tile" ? "tile" : "feature"} disk--${i}${cls ? ` ${esc(cls)}` : ""}" part="disk">`
    + `<span class="disk__shell" aria-hidden="true"><span class="disk__shutter"></span><span class="disk__window"></span></span>`
    + `<span class="disk__label"><span class="disk__no">${esc(no ? `SLOW ${no}` : "SLOWAPP")}</span>`
    + `<span class="disk__title">${esc(title)}</span></span></div>`;
}

/** The yellow diamond key the "Next card" button carries. */
const DIA = `<svg class="keyglyph" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">`
  + `<rect class="keyglyph__cap" x="1.5" y="1.5" width="21" height="21" stroke-width="3"/>`
  + `<path class="keyglyph__legend" d="M12 5.5 18.5 12 12 18.5 5.5 12Z"/></svg>`;

/** The screens: a deck per size (the first shown), a size picker when there are several. */
export function renderScreens(m) {
  if (!m.decks.length) return "";
  const pick = m.decks.length > 1
    ? `<div class="sizes" role="group" aria-label="Size" part="sizes">${m.decks.map((d, i) =>
      `<button class="btn btn--small" type="button" data-size="${i}" aria-pressed="${i === 0}">${esc(d.label)}</button>`).join("")}</div>`
    : "";
  const decks = m.decks.map((d, i) => {
    const wide = d.w > d.h * 1.5;
    return `<div class="deck${wide ? " deck--wide" : ""}" data-deck="${i}" data-w="${d.w}" data-h="${d.h}"${i ? " hidden" : ""}>`
      + `<div class="epd" data-epd part="screen-frame">`
      + d.cards.map((c, j) => `<img src="${esc(c.src)}" alt="${esc(c.alt)}" width="${c.w}" height="${c.h}"`
        + `${i ? ' loading="lazy"' : ""}${j ? " hidden" : ""} data-card part="screen">`).join("")
      + `<span class="epd__flash" aria-hidden="true"></span></div>`
      + (d.cards.length > 1 ? `<button class="btn btn--small" type="button" data-tap part="button">${DIA} Next card</button>` : "")
      + `</div>`;
  }).join("");
  return `${pick}${decks}${m.note ? `<p class="note">${esc(m.note)}</p>` : ""}`;
}

/** What the app may touch: internet, secrets, memory; then the other grants, one line each. */
export function renderGrants(m) {
  if (!m.touches) return "";
  const row = (k, v) => `<div><dt>${k}</dt><dd>${esc(v || "Not measured yet")}</dd></div>`;
  return `<dl class="touches" part="grants">${row("Internet", m.touches.internet)}${row("Secrets", m.touches.secrets)}${row("Memory", m.touches.memory)}</dl>`
    + (m.also.length ? `<ul class="also" part="also">${m.also.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : "");
}

/** Version, licence, each feed's sizes and inks, the download: only what the bundle has. */
export function renderFacts(m) {
  if (!m.facts.length) return "";
  const inks = (xs) => xs.length ? ` <span class="inks" aria-label="Inks: ${esc(xs.join(", "))}">${xs.map((i) => `<i class="ink ink--${i}" title="${i}"></i>`).join("")}</span>` : "";
  const sizes = (xs) => xs.length ? `<ul class="sizelist">${xs.map((s) => s.ok ? `<li>${esc(s.label)}</li>` : `<li class="no"${s.error ? ` title="${esc(s.error)}"` : ""}>${esc(s.label)}: no card at this size</li>`).join("")}</ul>` : "";
  return `<dl class="facts" part="facts">${m.facts.map((f) =>
    `<div><dt>${esc(f.label)}</dt><dd>${esc(f.value)}${inks(f.inks || [])}${sizes(f.sizes || [])}</dd></div>`).join("")}</dl>`;
}

/** The whole sheet: the disk half in the drive, then the screens beside the words. */
export function renderSheet(m, { head = true } = {}) {
  const sub = [m.no && `SLOW ${m.no}`, m.version && !m.no && `v${m.version}`, m.author && `by ${m.author}`].filter(Boolean).join(" · ");
  const headHtml = head
    ? `<section class="head" part="head" aria-labelledby="app-title">`
      + (m.crumb ? `<p class="crumb head__crumb"><a href="${esc(m.crumb.href)}">${esc(m.crumb.label)}</a></p>` : "")
      + renderDisk({ no: m.no, title: m.title, ink: m.ink, cls: "head__disk" })
      + `<div class="head__bar" part="bar"><h1 id="app-title" class="h2">${esc(m.title)}</h1>${sub ? `<p>${esc(sub)}</p>` : ""}</div></section>`
    : "";
  const screens = renderScreens(m);
  const grants = renderGrants(m);
  const facts = renderFacts(m);
  const about = (m.about ? `<p class="lede">${esc(m.about)}</p>` : "")
    + (grants ? `<h2 class="h3">What it may touch</h2>${grants}` : "")
    + (facts ? `<h2 class="h3">Sizes and inks</h2>${facts}` : "")
    + (m.links.length ? `<div class="actions" part="actions">${m.links.map((l) =>
      `<a class="btn${l.tone ? ` btn--${l.tone}` : ""}" href="${esc(l.href)}" part="button">${esc(l.label)}</a>`).join("")}</div>` : "");
  return `${headHtml}<section class="body${screens ? "" : " body--words"}" part="body">`
    + (screens ? `<div class="cards" data-screens part="screens">${screens}</div>` : "")
    + `<div class="about" part="about">${about}</div></section>`;
}

/**
 * Declarative Shadow DOM for a server-rendered element: `<slowapp-sheet>` + this + the light DOM
 * fallback. `css` is the URL of elements.css (a <link>, which a strict CSP allows); the element
 * swaps it for its constructed stylesheet when it upgrades.
 */
export function shadowTemplate(inner, { css } = {}) {
  return `<template shadowrootmode="open">${css ? `<link rel="stylesheet" href="${esc(safeUrl(css))}">` : ""}${inner}</template>`;
}
