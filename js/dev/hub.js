// A mock hub for `slowapp dev` and the tests: the hub side of the bridge calls, with the real
// hub's rules (epaper-dashboard crates/slowhub/src/appui.rs, settings.rs): docs with revisions
// (a stale write is a conflict), job-only docs, max_kb, write-only secrets, settings checked
// against [settings], job args checked by type, on_change jobs debounced 2 s, and a job's doc
// writes applied only if the doc hasn't moved since it started.
//
// The chrome's own calls (ui.*, device.preview) are the dev chrome's, as they are the hub
// page's; CHROME_CALLS lists them.

export const HUB_CALLS = [
  "connect", "docs.get", "docs.put", "docs.watch", "settings.get", "settings.set",
  "secrets.status", "secrets.set", "secrets.clear", "jobs.run", "events.watch", "backend.fetch",
];
export const CHROME_CALLS = ["ui.title", "ui.toast", "ui.confirm", "ui.resize", "device.preview"];

const MAX_SECRET = 8 * 1024;
const MAX_ARG_STRING = 4096;

export class HubError extends Error {
  constructor(code, message, extra = {}) {
    super(message);
    this.code = code;
    Object.assign(this, extra);
  }
  toJSON() { return { code: this.code, message: this.message, ...this.extra() }; }
  extra() {
    const { code, message, stack, ...rest } = this; // eslint-disable-line no-unused-vars
    return rest;
  }
}

/** Check settings against a [settings] schema; the hub's rules (settings.rs). */
export function checkSettings(schema, values) {
  const errors = {};
  if (!values || typeof values !== "object" || Array.isArray(values)) return { errors: { "": "settings must be an object" } };
  const out = {};
  for (const [k, v] of Object.entries(values)) {
    const s = schema[k];
    if (!s) { errors[k] = "not a setting of this app"; continue; }
    if (v === null) { if (s.optional) continue; errors[k] = "required"; continue; }
    const num = typeof v === "number";
    const ok = { string: typeof v === "string", boolean: typeof v === "boolean", number: num && Number.isFinite(v),
      integer: num && Number.isInteger(v), choice: typeof v === "string" && (s.choices || []).includes(v) }[s.type];
    if (!ok) { errors[k] = s.type === "choice" ? `one of ${(s.choices || []).join(", ")}` : `must be a ${s.type}`; continue; }
    if (num && ((s.min != null && v < s.min) || (s.max != null && v > s.max))) { errors[k] = `between ${s.min ?? "-∞"} and ${s.max ?? "∞"}`; continue; }
    out[k] = v;
  }
  for (const [k, s] of Object.entries(schema)) {
    if (!(k in out) && !(k in errors) && !s.optional && s.default === undefined && !(k in values)) errors[k] = "required";
  }
  return Object.keys(errors).length ? { errors } : { values: out };
}

/** Check job args against a job's `args`: an object of declared names, each of its type. */
export function checkArgs(job, args) {
  const decl = job.args || {};
  if (args == null) return { values: {} };
  if (typeof args !== "object" || Array.isArray(args)) return { errors: { "": "args must be an object" } };
  const errors = {};
  for (const [k, v] of Object.entries(args)) {
    const t = decl[k];
    if (!t) { errors[k] = `${job.name} takes no argument ${k}`; continue; }
    const ok = { string: typeof v === "string" && v.length <= MAX_ARG_STRING, number: typeof v === "number",
      integer: Number.isInteger(v), boolean: typeof v === "boolean" }[t];
    if (!ok) errors[k] = `must be a ${t}`;
  }
  return Object.keys(errors).length ? { errors } : { values: args };
}

/**
 * @param manifest   the parsed slowapp.toml
 * @param state      {docs: {name: {rev, value, at}}, secrets: [names], settings: {}} (persisted by the caller,
 *                   all but `secrets`: their values live only in memory, so set-ness goes with them)
 * @param runJob     async (name, {args, docs, settings, secrets}) => {exit, result, docs, log, feeds}
 *                   (`feeds: false` when it wrote no feed: exit 0 is then "unchanged", as on the hub)
 * @param emit       (event) => void: {event: "doc"|"run", ...}
 * @param save       () => void after any change to state
 */
export class MockHub {
  constructor({ manifest, state = {}, runJob, emit = () => {}, save = () => {}, now = () => new Date(), debounceMs = 2000 }) {
    this.m = manifest;
    this.state = { docs: {}, secrets: [], settings: {}, ...state };
    this.runJob = runJob || (async () => ({ exit: 0, result: null, log: "dev: no job runner configured" }));
    this.emit = emit;
    this.save = save;
    this.now = now;
    this.debounceMs = debounceMs;
    this.timers = new Map();
    this.runSeq = 0;
  }

  get app() { return this.m.app || {}; }
  get docDecls() { return this.m.docs || {}; }
  get jobs() { return this.m.job || []; }

  info() {
    const docs = Object.fromEntries(Object.entries(this.docDecls).map(([n, d]) => [n, { writer: d.writer || "both", max_kb: d.max_kb || 64 }]));
    return {
      app: this.app.id, title: this.app.title || this.app.id, contract: this.app.contract, tz: process.env.TZ || "America/Vancouver",
      settings_schema: this.m.settings || {}, settings: this.state.settings, docs,
      secrets: this.secretStatus(), jobs: this.jobs.map((j) => ({ name: j.name, args: j.args || {} })),
      backend: !!this.m.ui?.backend,
    };
  }

  secretStatus() {
    const req = this.app.secrets || [], opt = this.app.optional_secrets || [];
    return [...req.map((n) => [n, false]), ...opt.map((n) => [n, true])]
      .map(([name, optional]) => ({ name, optional, set: this.state.secrets.includes(name) }));
  }

  doc(name) {
    if (!this.docDecls[name]) throw new HubError("not_found", "no such doc");
    return this.state.docs[name] || { rev: 0, value: null, at: null };
  }

  writeDoc(name, value, by) {
    const cur = this.doc(name);
    const d = { rev: cur.rev + 1, value, at: this.now().toISOString() };
    this.state.docs[name] = d;
    this.save();
    this.emit({ event: "doc", name, by, ...d });
    return d.rev;
  }

  async handle(call, args = []) {
    switch (call) {
      case "connect": return this.info();
      case "docs.get": return this.doc(args[0]);
      case "docs.put": {
        const [name, value, rev] = args;
        const decl = this.docDecls[name];
        if (!decl) throw new HubError("not_found", "no such doc");
        if (decl.writer === "job") throw new HubError("forbidden", "only this app's jobs write this doc");
        const max = (decl.max_kb || 64) * 1024;
        if (Buffer.byteLength(JSON.stringify(value ?? null)) > max) throw new HubError("too_big", `this doc holds at most ${max / 1024} KiB`);
        const cur = this.doc(name);
        if (cur.rev !== rev) throw new HubError("conflict", "changed since you read it", { rev: cur.rev, value: cur.value });
        const r = this.writeDoc(name, value ?? null, "ui");
        for (const job of decl.on_change || []) this.onChange(job);
        return { rev: r };
      }
      case "docs.watch": this.doc(args[0]); return true;
      case "settings.get": return this.state.settings;
      case "settings.set": {
        const schema = this.m.settings || {};
        if (!Object.keys(schema).length) throw new HubError("invalid", "this app has no settings");
        const r = checkSettings(schema, args[0]);
        if (r.errors) throw new HubError("invalid", "some settings aren't valid", { errors: r.errors });
        this.state.settings = r.values;
        this.save();
        return r.values;
      }
      case "secrets.status": return this.secretStatus();
      case "secrets.set":
      case "secrets.clear": {
        const [name, value] = args;
        if (!this.secretStatus().some((s) => s.name === name)) throw new HubError("invalid", "not one of this app's secrets");
        const set = call === "secrets.set";
        if (set && (typeof value !== "string" || !value.length || Buffer.byteLength(value) > MAX_SECRET)) throw new HubError("invalid", `a secret is 1 to ${MAX_SECRET} bytes`);
        this.state.secrets = this.state.secrets.filter((n) => n !== name).concat(set ? [name] : []);
        this.secretValues = { ...(this.secretValues || {}), [name]: set ? value : undefined };
        this.save();
        return { name, set };
      }
      case "jobs.run": return this.run(args[0], args[1], "manual");
      case "events.watch": return true;
      case "backend.fetch": throw new HubError("no_backend", "this app has no backend");
      default: throw new HubError("unknown_call", `no call ${call}`);
    }
  }

  onChange(job) {
    clearTimeout(this.timers.get(job));
    this.timers.set(job, setTimeout(() => { this.timers.delete(job); this.run(job, {}, "docs").catch(() => {}); }, this.debounceMs));
  }

  /** Run a job: args checked, docs in, result and job-written docs out (if their rev held). */
  async run(name, args, reason, retried = false) {
    const job = this.jobs.find((j) => j.name === name);
    if (!job) throw new HubError("not_found", "no such job");
    const a = checkArgs(job, args);
    if (a.errors) throw new HubError("invalid", "bad arguments", { errors: a.errors });
    const run = `r_dev_${++this.runSeq}`;
    const revs = Object.fromEntries(Object.keys(this.docDecls).map((n) => [n, this.doc(n).rev]));
    const docs = Object.fromEntries(Object.keys(this.docDecls).filter((n) => this.state.docs[n]).map((n) => [n, this.state.docs[n].value]));
    this.emit({ event: "run", app: this.app.id, job: name, run, phase: "started", reason });
    let r;
    try {
      r = await this.runJob(name, { args: a.values, docs, settings: this.state.settings, secrets: this.secretValues || {}, reason });
    } catch (e) {
      r = { exit: 1, log: String(e?.stack || e) };
    }
    const exit = r.exit ?? 0;
    const ok = exit === 0 || exit === 3;
    const outcome = exit === 3 || (exit === 0 && r.feeds === false) ? "unchanged" : exit === 0 ? "new" : exit === 5 ? "needs_config" : exit === 4 ? "transient" : "failed";
    let conflict = false;
    if (ok) {
      for (const [n, v] of Object.entries(r.docs || {})) {
        const decl = this.docDecls[n];
        if (!decl || decl.writer === "ui") continue;
        if (this.doc(n).rev !== revs[n]) { conflict = true; continue; }
        if (JSON.stringify(this.doc(n).value) !== JSON.stringify(v)) this.writeDoc(n, v, "job");
      }
    }
    this.emit({ event: "run", app: this.app.id, job: name, run, phase: "ended", outcome });
    if (conflict && !retried) this.run(name, args, reason, true).catch(() => {});
    const lines = String(r.log || "").trim().split("\n");
    return { run, outcome, ok, exit, result: r.result ?? null, message: ok ? null : lines[lines.length - 1] || null };
  }
}
