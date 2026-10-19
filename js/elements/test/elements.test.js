// @slowboard/elements: the model and HTML from a real catalog bundle (the moon example's, from
// `slowapp catalog build`), the site's own input, escaping, and that the HTML and the built module
// keep to what a strict CSP allows (no inline script or style, no eval, no fetch).
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import * as elements from "../index.js";
import { css } from "../styles.js";
import { bytes, grantSize, renderSheet, safeUrl, sheetModel, shadowTemplate, surface } from "../render.js";
import { buildElements } from "../build.js";

const moon = JSON.parse(fs.readFileSync(new URL("./moon/catalog.json", import.meta.url)));
const schema = JSON.parse(fs.readFileSync(new URL("../../../sdk/slowapp_sdk/schema/catalog.schema.json", import.meta.url)));

/** What a strict CSP would refuse or a sanitiser would flag, in rendered HTML. */
function assertCspClean(html) {
  assert.doesNotMatch(html, /<script/i, "no script");
  assert.doesNotMatch(html, /<style/i, "no <style>");
  const tags = html.match(/<[^>]*>/g) || [];   // text is escaped, so every < starts a tag
  assert.ok(!tags.some((t) => /\sstyle=/i.test(t)), "no style attribute");
  assert.ok(!tags.some((t) => /\son[a-z]+=/i.test(t)), "no event-handler attribute");
  assert.doesNotMatch(html, /javascript:/i, "no javascript: URL");
}

test("the fixture is a catalog bundle of the version the elements read", () => {
  assert.equal(moon.catalog, schema.properties.catalog.const);
  for (const k of schema.required) assert.ok(k in moon, k);
});

test("a bundle becomes a deck per size, the whole panel, and the grants in words", () => {
  const m = sheetModel({ catalog: moon, base: "/catalog/moon/" });
  assert.equal(m.title, "Moon");
  assert.equal(m.ink, "yellow");
  assert.equal(m.author, "mike-anderson");
  assert.deepEqual(m.decks.map((d) => d.id), ["452x444.k4", "456x444.k4", "1360x444.k4", "panel"]);
  assert.deepEqual(m.decks.map((d) => d.label), ["452×444", "456×444", "1360×444", "Whole panel"]);
  // The first good example's cards, home before detail, at the bundle's paths under base.
  assert.deepEqual(m.decks[0].cards.map((c) => c.src),
    ["/catalog/moon/screens/today/452x444.k4/phase/home.png", "/catalog/moon/screens/today/452x444.k4/phase/week.png"]);
  assert.equal(m.decks[0].cards[0].alt, "Moon, home card: Waning crescent");
  assert.deepEqual([m.decks[0].w, m.decks[0].h], [452, 444]);
  assert.deepEqual([m.decks[3].w, m.decks[3].h], [1360, 480]);
  assert.equal(m.note, "7 Oct 2026: a waning crescent, new moon on the 10th");
  assert.deepEqual(m.touches, { internet: "No", secrets: "None", memory: "48 MB" });
  assert.deepEqual(m.links, [{ href: "https://github.com/mike-anderson/slowapp-example", label: "Source on GitHub", tone: "black" }]);
  const feed = m.facts.find((f) => f.label === "Feed phase");
  assert.equal(feed.value, "any slot");
  assert.deepEqual(feed.inks, ["black", "white", "yellow", "red"]);
  assert.deepEqual(feed.sizes.map((s) => [s.label, s.ok]), [["452×444", true], ["456×444", true], ["1360×444", true]]);
  // A bare bundle is the same input.
  assert.deepEqual(sheetModel(moon).decks.map((d) => d.id), m.decks.map((d) => d.id));
});

test("the sheet's HTML: head, picker, decks, grants, details, links; nothing a CSP refuses", () => {
  const html = renderSheet(sheetModel({ catalog: moon, base: "/c/", no: "004" }));
  assertCspClean(html);
  assert.match(html, /<h1 id="app-title" class="h2">Moon<\/h1><p>SLOW 004 · by mike-anderson<\/p>/);
  assert.match(html, /class="disk disk--feature disk--yellow head__disk"/);
  assert.equal((html.match(/data-size="/g) || []).length, 4, "a button per size");
  assert.equal((html.match(/data-deck="/g) || []).length, 4);
  assert.match(html, /data-deck="1" data-w="456" data-h="444" hidden/, "only the first deck shows");
  assert.match(html, /loading="lazy"/, "the hidden sizes load when shown");
  assert.equal((html.match(/data-tap/g) || []).length, 3, "Next card on every deck with two cards or more (one whole-panel frame)");
  assert.match(html, /<dt>Memory<\/dt><dd>48 MB<\/dd>/);
  assert.match(html, /<h2 class="h3">The details<\/h2>/);
  assert.match(html, /<a class="btn btn--black" href="https:\/\/github.com\/mike-anderson\/slowapp-example" part="button">Source on GitHub<\/a>/);
  assert.doesNotMatch(renderSheet(sheetModel(moon), { head: false }), /class="head"/);
});

test("the site's input: its own cards, words and links, and no details it doesn't have", () => {
  const m = sheetModel({
    catalog: { app: { id: "reminders", title: "Reminders", author: "mike-anderson", ink: "red", about: "Water the plants." } },
    no: "002",
    cards: [{ src: "/panel/ask.png", alt: "Question card", synthetic: true }],
    touches: { internet: "No", secrets: "None", memory: "48 MB" },
    links: [{ href: "https://github.com/x/y", label: "Source on GitHub", tone: "black" }, { href: "/docs/slowapps#publishing-and-installing", label: "Add it to your hub" }],
    crumb: { href: "/slowapps", label: "Slowapps" },
  });
  const html = renderSheet(m);
  assertCspClean(html);
  assert.match(html, /^<section class="head" part="head" aria-labelledby="app-title"><p class="crumb head__crumb"><a href="\/slowapps">Slowapps<\/a><\/p>/);
  assert.match(html, /<span class="disk__no">SLOW 002<\/span><span class="disk__title">Reminders<\/span>/);
  assert.match(html, /<img src="\/panel\/ask.png" alt="Question card" width="452" height="480" data-card part="screen">/);
  assert.doesNotMatch(html, /data-tap|data-size/, "one card: no Next card, one size: no picker");
  assert.match(html, /<p class="note">Demo card, drawn in the app&#39;s style.<\/p>/);
  assert.doesNotMatch(html, /The details/);
  assert.match(html, /<a class="btn" href="\/docs\/slowapps#publishing-and-installing" part="button">Add it to your hub<\/a>/);
});

test("what a host has without a bundle: words and grants, feeds with their sizes and ink sets", () => {
  const m = sheetModel({ catalog: {
    app: { id: "weather", title: "Weather", version: "0.1.8" },
    grants: { network: "egress", memory: "256m", secrets: ["key"], optional_secrets: ["extra"], prompts: true, ui: false, backend: false, imports: [], exports: [], events: [] },
    feeds: [{ name: "home", size: "slot", ink_sets: ["k4"] }, { name: "sleep", size: "1284x340", ink_sets: ["g16"] }],
  } });
  assert.equal(m.decks.length, 0);
  assert.deepEqual(m.touches, { internet: "Yes, outgoing only", secrets: "key, extra (optional)", memory: "256 MB" });
  assert.deepEqual(m.also, ["Asks questions on the panel, answered with a key"]);
  assert.deepEqual(m.facts.map((f) => [f.label, f.value]), [["Version", "0.1.8"], ["Feed home", "any slot (k4)"], ["Feed sleep", "1284×340 (g16)"]]);
  assert.deepEqual(m.facts[2].inks, ["black", "white", "grey"]);
  const html = renderSheet(m);
  assert.match(html, /<section class="body body--words" part="body"><div class="about"/, "no screens column");
  assert.match(html, /<p>v0.1.8<\/p>/);
});

test("text from a bundle is escaped and only http(s) or relative URLs get through", () => {
  const m = sheetModel({ catalog: { app: { title: "<img src=x onerror=alert(1)>", about: "a & b", repo: "javascript:alert(1)" } },
    cards: [{ src: "javascript:alert(1)", alt: '"><script>' }], links: [{ href: "data:text/html,x", label: "x" }, { href: "//evil.example", label: "y" }] });
  const html = renderSheet(m);
  assertCspClean(html);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html, /a &amp; b/);
  assert.match(html, /alt="&quot;&gt;&lt;script&gt;"/);
  assert.match(html, /<img src="" /);
  assert.deepEqual(m.links, []);
  assert.equal(safeUrl("https://x.example/a"), "https://x.example/a");
  assert.equal(safeUrl("/a/b.png"), "/a/b.png");
  assert.equal(safeUrl("screens/a.png"), "screens/a.png");
});

test("formatting", () => {
  assert.equal(grantSize("256m"), "256 MB");
  assert.equal(grantSize("1g"), "1 GB");
  assert.equal(grantSize("512k"), "512 KB");
  assert.equal(bytes(999), "999 B");
  assert.equal(bytes(1234567), "1.2 MB");
  assert.equal(bytes(123456789), "123 MB");
  assert.deepEqual(surface("1284x340.g16"), { id: "1284x340.g16", w: 1284, h: 340, inks: "g16", label: "1284×340 grey" });
  assert.equal(surface("slot"), null);
});

test("in Node the module defines nothing and imports cleanly; the shadow template links the CSS", () => {
  assert.equal(typeof elements.define, "function");
  assert.deepEqual(Object.keys(elements.ELEMENTS), ["slowapp-sheet", "slowapp-screens", "slowapp-grants", "slowapp-facts", "slowapp-disk"]);
  assert.equal(elements.stylesheet(), null, "no CSSOM in Node");
  const reg = new Map();
  elements.define({ get: (t) => reg.get(t), define: (t, c) => reg.set(t, c) });
  assert.equal(reg.get("slowapp-sheet"), elements.SlowappSheet);
  assert.equal(shadowTemplate("<p>x</p>", { css: "/e.css" }), '<template shadowrootmode="open"><link rel="stylesheet" href="/e.css"><p>x</p></template>');
});

test("the stylesheet uses only the host's tokens and its own private names", () => {
  const vars = new Set([...css.matchAll(/var\((--[a-z0-9-]+)/gi)].map((m) => m[1]));
  const host = [...vars].filter((v) => !v.startsWith("--_"));
  const allowed = new Set(["--ink-black", "--ink-white", "--ink-yellow", "--ink-red", "--paper", "--text", "--keyline", "--mark", "--muted",
    "--solid", "--on-solid", "--font-display", "--font-button", "--font-code", "--line", "--step-1", "--ease-out", "--slowapp-gutter", "--slowapp-band", "--slowapp-bar",
    "--bg", "--fg", "--body", "--kl", "--dw"]);
  assert.deepEqual(host.filter((v) => !allowed.has(v)), []);
  assert.doesNotMatch(css, /@import|url\((?!#)/, "no fetches from the stylesheet");
});

test("the build: one module whose first line carries the sha256 of the rest, and elements.css", async (t) => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "sb-elements-"));
  t.after(() => fs.rmSync(out, { recursive: true, force: true }));
  const r = await buildElements(out);
  const js = fs.readFileSync(r.js, "utf8");
  const nl = js.indexOf("\n");
  const m = /^\/\*! @slowboard\/elements (\d+\.\d+\.\d+) sha256:([0-9a-f]{64}) \*\/$/.exec(js.slice(0, nl));
  assert.ok(m, js.slice(0, nl));
  assert.equal(m[1], JSON.parse(fs.readFileSync(new URL("../package.json", import.meta.url))).version);
  assert.equal(m[1], elements.VERSION, "index.js's VERSION is the package's");
  assert.equal(crypto.createHash("sha256").update(js.slice(nl + 1)).digest("hex"), m[2]);
  assert.doesNotMatch(js, /\beval\(|new Function|\bfetch\(|XMLHttpRequest|\bimport\(|document\.write|insertAdjacentHTML\(.*<script/);
  assert.doesNotMatch(js, /^import /m, "self-contained: no imports");
  assert.match(js, /^export \{/m);
  assert.ok(fs.readFileSync(r.css, "utf8").endsWith(css.trimStart()));
  // The built module works in Node like the source.
  const built = await import(r.js);
  assert.equal(built.renderSheet(built.sheetModel(moon)), renderSheet(sheetModel(moon)));
});
