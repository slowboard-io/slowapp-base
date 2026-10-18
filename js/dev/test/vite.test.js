// The Vite plugin: the bundle cap measures the inlined single file, and the mock hub's endpoints
// answer only this server's own pages.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { build } from "vite";

import { sameOrigin, slowboard } from "../vite.js";

function app() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "slowapp-vite-"));
  fs.writeFileSync(path.join(root, "index.html"), '<!doctype html><html><body><script type="module" src="./main.js"></script></body></html>');
  fs.writeFileSync(path.join(root, "main.js"), `document.body.textContent = ${JSON.stringify("x".repeat(8000))};`);
  return root;
}

const run = (root, maxBytes) => build({ root, logLevel: "silent", configFile: false, plugins: [slowboard({ maxBytes })], build: { outDir: path.join(root, "dist") } });

test("the cap counts the script inlined into index.html", async (t) => {
  const root = app();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  await run(root, 1024 * 1024);
  const html = fs.readFileSync(path.join(root, "dist", "index.html"), "utf8");
  assert.ok(html.includes("x".repeat(8000)), "the script is inlined");
  await assert.rejects(run(root, 4000), /index\.html is \d+ bytes; the hub serves at most 4000/);
});

test("the mock hub's endpoints refuse other sites and sandboxed frames", () => {
  const req = (headers) => ({ headers: { host: "localhost:5173", ...headers } });
  assert.ok(sameOrigin(req({ origin: "http://localhost:5173", "sec-fetch-site": "same-origin" })));
  assert.ok(sameOrigin(req({}))); // curl
  assert.ok(sameOrigin(req({ "sec-fetch-site": "none" })));
  assert.ok(!sameOrigin(req({ origin: "null", "sec-fetch-site": "cross-site" })));
  assert.ok(!sameOrigin(req({ origin: "null" })));
  assert.ok(!sameOrigin(req({ origin: "https://evil.example" })));
  assert.ok(!sameOrigin(req({ "sec-fetch-site": "same-site" })));
});
