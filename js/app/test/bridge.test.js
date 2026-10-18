// @slowboard/app against the dev mock hub, over a real MessageChannel: the client's calls, its
// errors, doc watches, the handshake, and that the protocol lists agree everywhere.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

import { BridgeError, CALLS, PROTOCOL, connect, fromPort } from "../index.js";
import { CHROME_CALLS, HUB_CALLS, MockHub } from "../../dev/hub.js";

const protocol = JSON.parse(fs.readFileSync(new URL("../protocol.json", import.meta.url)));

const MANIFEST = {
  app: { id: "notes", title: "Notes", contract: 4, optional_secrets: ["token"] },
  settings: { days: { type: "integer", default: 5, min: 1, max: 14 } },
  ui: { entry: "/ui/index.html" },
  docs: { notes: { max_kb: 1 }, stats: { writer: "job" } },
  job: [{ name: "echo", args: { text: "string" } }],
};

/** A chrome in a test: the hub's calls to `hub`, the chrome's own answered here. */
function wire(hub) {
  const ch = new MessageChannel();
  const chromePort = ch.port1;
  const pushed = (m) => chromePort.postMessage(m);
  hub.emit = pushed;
  chromePort.onmessage = async ({ data: m }) => {
    try {
      const value = CHROME_CALLS.includes(m.call) ? true : await hub.handle(m.call, m.args);
      chromePort.postMessage({ id: m.id, ok: true, value });
    } catch (e) {
      const { message, code, stack, ...rest } = e; // eslint-disable-line no-unused-vars
      chromePort.postMessage({ id: m.id, ok: false, error: { code, message, ...rest } });
    }
  };
  const app = fromPort(ch.port2, { timeoutMs: 2000 });
  return { app, close: () => { ch.port1.close(); ch.port2.close(); } };
}

test("the protocol lists agree: protocol.json, the client, the mock hub and the dev chrome", () => {
  assert.equal(PROTOCOL, protocol.protocol);
  assert.deepEqual([...CALLS], protocol.calls);
  assert.deepEqual([...HUB_CALLS, ...CHROME_CALLS].sort(), [...protocol.calls].sort());
  const chrome = fs.readFileSync(new URL("../../dev/chrome.js", import.meta.url), "utf8");
  for (const c of CHROME_CALLS) assert.ok(chrome.includes(`"${c}"`), `dev chrome handles ${c}`);
});

test("docs: read, write over a revision, a stale write is a conflict with the current doc", async () => {
  const hub = new MockHub({ manifest: MANIFEST, runJob: async () => ({ exit: 0 }) });
  const { app, close } = wire(hub);
  assert.deepEqual(await app.docs.get("notes"), { rev: 0, value: null, at: null });
  assert.deepEqual(await app.docs.put("notes", ["milk"], 0), { rev: 1 });
  const seen = [];
  app.docs.watch("notes", (d) => seen.push(d.rev));
  await assert.rejects(app.docs.put("notes", ["eggs"], 0), (e) => {
    assert.ok(e instanceof BridgeError);
    assert.equal(e.code, "conflict");
    assert.equal(e.rev, 1);
    assert.deepEqual(e.value, ["milk"]);
    return true;
  });
  await app.docs.put("notes", ["milk", "eggs"], 1);
  await new Promise((r) => setTimeout(r, 20));
  assert.deepEqual(seen, [2]);
  await assert.rejects(app.docs.put("stats", 1, 0), { code: "forbidden" });
  await assert.rejects(app.docs.put("notes", "x".repeat(2000), 2), { code: "too_big" });
  await assert.rejects(app.docs.get("other"), { code: "not_found" });
  close();
});

test("settings, secrets, jobs and the rest", async () => {
  let ran;
  const hub = new MockHub({
    manifest: MANIFEST,
    runJob: async (name, ctx) => { ran = ctx; return { exit: 0, result: { echo: ctx.args.text, secret: !!ctx.secrets.token } }; },
  });
  const { app, close } = wire(hub);
  const info = await app.call("connect");
  assert.equal(info.contract, 4);
  assert.deepEqual(info.secrets, [{ name: "token", optional: true, set: false }]);
  assert.deepEqual(await app.settings.set({ days: 7 }), { days: 7 });
  await assert.rejects(app.settings.set({ days: 99 }), (e) => e.code === "invalid" && "days" in e.errors);
  assert.deepEqual(await app.secrets.set("token", "hunter2"), { name: "token", set: true });
  assert.deepEqual((await app.secrets.status())[0].set, true);
  assert.ok(!JSON.stringify(hub.state).includes("hunter2"), "the saved state never holds a value");
  const r = await app.jobs.run("echo", { text: "hi" });
  assert.equal(r.ok, true);
  assert.deepEqual(r.result, { echo: "hi", secret: true });
  assert.deepEqual(ran.settings, { days: 7 });
  await assert.rejects(app.jobs.run("echo", { text: 1 }), { code: "invalid" });
  await assert.rejects(app.jobs.run("nope"), { code: "not_found" });
  await assert.rejects(app.backend.fetch("/x"), { code: "no_backend" });
  assert.equal(await app.ui.toast("hi"), true);
  await assert.rejects(app.call("bogus"), { code: "unknown_call" });
  close();
});

test("a job's doc write applies, and loses to a write made while it ran", async () => {
  let release;
  const hub = new MockHub({
    manifest: { ...MANIFEST, docs: { notes: {} } },
    runJob: (name, ctx) => new Promise((ok) => { release = () => ok({ exit: 0, docs: { notes: [...(ctx.docs.notes || []), "job"] } }); }),
  });
  const { app, close } = wire(hub);
  const runs = [];
  app.events.runs((e) => runs.push(`${e.job}:${e.phase}`));
  const job = app.jobs.run("echo", {});
  await new Promise((r) => setTimeout(r, 10));
  release();
  await job;
  assert.deepEqual((await app.docs.get("notes")).value, ["job"]);
  // This time the UI writes while the job runs: the job's write is refused, and it runs again.
  const again = app.jobs.run("echo", {});
  await new Promise((r) => setTimeout(r, 10));
  await app.docs.put("notes", ["ui"], 1);
  release();
  await again;
  assert.deepEqual((await app.docs.get("notes")).value, ["ui"]);
  await new Promise((r) => setTimeout(r, 10));
  release(); // the re-run, on the UI's version
  await new Promise((r) => setTimeout(r, 20));
  assert.deepEqual((await app.docs.get("notes")).value, ["ui", "job"]);
  assert.deepEqual(runs.filter((r) => r.endsWith("started")).length, 3);
  close();
});

test("on_change runs once after a burst of writes", async () => {
  const jobs = [];
  const hub = new MockHub({
    manifest: { ...MANIFEST, docs: { notes: { on_change: ["echo"] } } },
    runJob: async (name) => { jobs.push(name); return { exit: 0 }; },
    debounceMs: 30,
  });
  const { app, close } = wire(hub);
  for (let i = 0; i < 3; i++) await app.docs.put("notes", [i], i);
  await new Promise((r) => setTimeout(r, 80));
  assert.deepEqual(jobs, ["echo"]);
  close();
});

test("max_kb counts UTF-8 bytes, and outcomes are the hub's: 0 new (unchanged with no feed), 3 unchanged", async () => {
  const exits = [{ exit: 0 }, { exit: 0, feeds: false }, { exit: 3 }, { exit: 4 }, { exit: 5 }, { exit: 1 }];
  const hub = new MockHub({ manifest: MANIFEST, runJob: async () => exits.shift() });
  await assert.rejects(hub.handle("docs.put", ["notes", "é".repeat(600), 0]), { code: "too_big" }); // 602 chars, 1202 bytes
  const outcomes = [];
  for (let i = 0; i < 6; i++) outcomes.push((await hub.handle("jobs.run", ["echo", {}])).outcome);
  assert.deepEqual(outcomes, ["new", "unchanged", "unchanged", "transient", "needs_config", "failed"]);
});

test("a refused watch is reported, and asked again by the next watcher", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] }); // the report's throw stays queued
  const asked = [];
  const ch = new MessageChannel();
  ch.port1.onmessage = ({ data: m }) => {
    asked.push(m.call);
    ch.port1.postMessage({ id: m.id, ok: false, error: { code: "not_found", message: "no such doc" } });
  };
  const app = fromPort(ch.port2);
  return new Promise((done) => {
    app.docs.watch("nope", () => {});
    app.events.runs(() => {});
    setImmediate(() => setImmediate(() => {
      app.docs.watch("nope", () => {});
      app.events.runs(() => {});
      setImmediate(() => {
        assert.deepEqual(asked, ["docs.watch", "events.watch", "docs.watch", "events.watch"]);
        ch.port1.close();
        done();
      });
    }));
  });
});

test("connect waits for the chrome's port, checks the protocol, and times out without a hub", async () => {
  const listeners = new Set();
  const parent = {};
  const win = { parent, addEventListener: (_t, f) => listeners.add(f), removeEventListener: (_t, f) => listeners.delete(f) };
  const hub = new MockHub({ manifest: MANIFEST });
  const ch = new MessageChannel();
  ch.port1.onmessage = async ({ data: m }) => ch.port1.postMessage({ id: m.id, ok: true, value: { ...(await hub.handle(m.call, m.args)), theme: "dark", tokens: { "--paper": "#141414" } } });
  const pending = connect({ win, waitMs: 1000 });
  for (const f of listeners) f({ source: {}, data: { slowboard: "connect", protocol: 1 }, ports: [new MessageChannel().port1] }); // not from parent: ignored
  for (const f of [...listeners]) f({ source: parent, data: { slowboard: "connect", protocol: 1 }, ports: [ch.port2] });
  const app = await pending;
  assert.equal(app.info.title, "Notes");
  let theme;
  app.onTheme((t) => { theme = t.theme; });
  assert.equal(theme, "dark");
  ch.port1.close();

  await assert.rejects(connect({ win: { ...win, parent: {} }, waitMs: 20 }), { code: "no_hub" });
  const bad = connect({ win, waitMs: 1000 });
  for (const f of [...listeners]) f({ source: parent, data: { slowboard: "connect", protocol: 2 }, ports: [new MessageChannel().port1] });
  await assert.rejects(bad, { code: "protocol" });
});
