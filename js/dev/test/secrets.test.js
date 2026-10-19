// @slowboard/dev, contract 6: what a dev run's /run/secrets looks like, a sync run's artifacts kept
// for the next render, and the grants per job.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { jobSpec } from "../hub.js";
import { keepArtifacts, writeSecrets } from "../vite.js";

test("values as files, oauth tokens as <name>.json or <name>/<account>.json", () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "sb-sec-"));
  writeSecrets(d, { ai_key: "sk-1", unset: null }, {
    github: { access_token: "t", expires_at: "x", scopes: [] },
    google: [{ account: "a@example.com", access_token: "ga", expires_at: "x", scopes: ["email"] }],
  });
  assert.deepEqual(fs.readdirSync(d).sort(), ["ai_key", "github.json", "google"]);
  assert.equal(fs.readFileSync(path.join(d, "ai_key"), "utf8"), "sk-1");
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(d, "google", "a@example.com.json"))), { access_token: "ga", expires_at: "x", scopes: ["email"] });
});

test("a sync run's artifacts replace the kept ones whole; others stay", () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "sb-out-"));
  const keep = fs.mkdtempSync(path.join(os.tmpdir(), "sb-keep-"));
  fs.mkdirSync(path.join(keep, "agenda"));
  fs.writeFileSync(path.join(keep, "agenda", "old.json"), "1");
  fs.mkdirSync(path.join(keep, "other"));
  fs.mkdirSync(path.join(out, "artifacts", "agenda"), { recursive: true });
  fs.writeFileSync(path.join(out, "artifacts", "agenda", "agenda.json"), "2");
  assert.deepEqual(keepArtifacts(out, keep), ["agenda"]);
  assert.deepEqual(fs.readdirSync(path.join(keep, "agenda")), ["agenda.json"]);
  assert.ok(fs.existsSync(path.join(keep, "other")));
});

test("jobSpec: the kit's rules", () => {
  const c6 = { app: { contract: 6, network: "egress" }, job: [{ name: "sync", kind: "sync", secrets: ["k"] }, { name: "render", secrets: ["k"] }] };
  assert.deepEqual(jobSpec(c6, "sync"), { kind: "sync", network: "egress", secrets: ["k"] });
  assert.deepEqual(jobSpec(c6, "render"), { kind: "render", network: "none", secrets: [] });
  const c5 = { app: { contract: 5, network: "egress", secrets: ["a"], optional_secrets: ["b"] }, job: [{ name: "render" }] };
  assert.deepEqual(jobSpec(c5, "render"), { kind: null, network: "egress", secrets: ["a", "b"] });
});
