// A mock hub for `slowapp dev` and the tests: the hub side of the bridge calls, with the real
// hub's rules (epaper-dashboard crates/slowhub/src/appui.rs, settings.rs): docs with revisions
// (a stale write is a conflict), job-only docs, max_kb, write-only secrets, settings checked
// against [settings], job args checked by type, on_change jobs debounced 2 s, and a job's doc
// writes applied only if the doc hasn't moved since it started.
//
// Protocol 2 (contract 6): secrets have a kind. A value is set and cleared as before; an oauth
// secret is connected with secrets.connect, which here is faked: it answers a dev-server link,
// and opening it (or completeConnect) "signs in" an account with the provider's scopes. Each run
// gets only its job's secrets (jobSpec), oauth ones as dev access tokens, and last_used follows.
//
// The chrome's own calls (ui.*, device.preview) are the dev chrome's, as they are the hub
// page's; CHROME_CALLS lists them.

export const HUB_CALLS = [
  "connect", "docs.get", "docs.put", "docs.watch", "settings.get", "settings.set",
  "secrets.status", "secrets.set", "secrets.clear", "secrets.connect", "jobs.run", "events.watch", "backend.fetch",
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

/**
 * What a manifest grants one job (slowapp_kit/manifest.py's job_spec): contract 6, a sync job its
 * own network and secrets and a render job neither; before 6, every job the app's.
 */
export function jobSpec(manifest, name) {
  const app = manifest.app || {};
  const j = (manifest.job || []).find((x) => x.name === name) || {};
  if ((app.contract ?? 3) < 6) {
    return { kind: null, network: app.network || "none", secrets: [...(app.secrets || []), ...(app.optional_secrets || [])] };
  }
  if (j.kind !== "sync") return { kind: "render", network: "none", secrets: [] };
  return { kind: "sync", network: j.network || app.network || "none", secrets: [...(j.secrets || [])] };
}

/** Every secret the manifest declares: [{name, optional, kind, label, help, auth, multiple}]. */
export function secretDecls(manifest) {
  const app = manifest.app || {};
  return [
    ...(app.secrets || []).map((name) => ({ name, optional: false, kind: "value" })),
    ...(app.optional_secrets || []).map((name) => ({ name, optional: true, kind: "value" })),
    ...Object.entries(manifest.secrets || {}).map(([name, s]) => ({
      name, optional: !!s.optional, kind: s.kind || "value", label: s.label, help: s.help, auth: s.auth, multiple: !!s.multiple,
    })),
  ];
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
    this.oauth ||= {};
    this.lastUsed ||= {};
    return secretDecls(this.m).map((d) => {
      const s = { name: d.name, optional: d.optional, set: this.state.secrets.includes(d.name), kind: d.kind, last_used: this.lastUsed[d.name] || null };
      if (d.label) s.label = d.label;
      if (d.help) s.help = d.help;
      if (d.kind === "oauth") {
        const accounts = this.oauth[d.name] || [];
        Object.assign(s, {
          set: accounts.length > 0, auth: d.auth, multiple: d.multiple,
          scopes: [...new Set(accounts.flatMap((a) => a.scopes))],
          granted_at: accounts.map((a) => a.granted_at).sort().at(-1) || null,
          accounts: accounts.map((a) => ({ ...a })),
        });
      }
      return s;
    });
  }

  secretDecl(name) {
    const d = secretDecls(this.m).find((s) => s.name === name);
    if (!d) throw new HubError("invalid", "not one of this app's secrets");
    return d;
  }

  emitSecret(name) {
    const s = this.secretStatus().find((x) => x.name === name);
    this.emit({ event: "secret", ...s });
    return s;
  }

  /**
   * The provider's side of a faked sign-in: `account` (default dev@example.com) is connected
   * with the [auth] provider's scopes. A multiple secret adds it; any other replaces.
   */
  completeConnect(name, account = "dev@example.com") {
    const d = this.secretDecl(name);
    if (d.kind !== "oauth") throw new HubError("kind", "not an oauth secret");
    const scopes = [...(this.m.auth?.[d.auth]?.scopes || [])];
    const acct = { account, scopes, granted_at: this.now().toISOString(), last_used: null };
    this.oauth ||= {};
    const others = d.multiple ? (this.oauth[name] || []).filter((a) => a.account !== account) : [];
    this.oauth[name] = [...others, acct].sort((a, b) => a.account.localeCompare(b.account));
    return this.emitSecret(name);
  }

  /** What a job gets: {secrets: {name: value}, tokens: {name: token | [token]}}, its own only. */
  grants(job) {
    const spec = jobSpec(this.m, job);
    const secrets = {}, tokens = {};
    const at = this.now();
    const expires = new Date(at.getTime() + 3600e3).toISOString();
    for (const name of spec.secrets) {
      const d = secretDecls(this.m).find((s) => s.name === name);
      if (!d) continue;
      if (d.kind === "oauth") {
        const accts = this.oauth?.[name] || [];
        if (!accts.length) continue;
        const tok = (a) => ({ access_token: `dev-${name}-${a.account}`, expires_at: expires, scopes: a.scopes });
        tokens[name] = d.multiple ? accts.map((a) => ({ ...tok(a), account: a.account })) : tok(accts[0]);
        for (const a of accts) a.last_used = at.toISOString();
      } else if (this.secretValues?.[name] != null) {
        secrets[name] = this.secretValues[name];
      } else continue;
      this.lastUsed = { ...(this.lastUsed || {}), [name]: at.toISOString() };
    }
    return { secrets, tokens };
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
        const d = this.secretDecl(name);
        const set = call === "secrets.set";
        if (d.kind === "oauth") {
          if (set) throw new HubError("kind", "an oauth secret is connected, not set (secrets.connect)");
          this.oauth ||= {};
          this.oauth[name] = value == null ? [] : (this.oauth[name] || []).filter((a) => a.account !== value);
          return { name, set: this.emitSecret(name).set };
        }
        if (set && (typeof value !== "string" || !value.length || Buffer.byteLength(value) > MAX_SECRET)) throw new HubError("invalid", `a secret is 1 to ${MAX_SECRET} bytes`);
        this.state.secrets = this.state.secrets.filter((n) => n !== name).concat(set ? [name] : []);
        this.secretValues = { ...(this.secretValues || {}), [name]: set ? value : undefined };
        this.save();
        this.emitSecret(name);
        return { name, set };
      }
      case "secrets.connect": {
        const [name, opts] = args;
        if (this.secretDecl(name).kind !== "oauth") throw new HubError("kind", "a value secret is set, not connected (secrets.set)");
        const q = opts?.account ? `?account=${encodeURIComponent(opts.account)}` : "";
        return { url: `/__slowboard/connect/${encodeURIComponent(name)}${q}` };
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
    const { secrets, tokens } = this.grants(name);
    try {
      r = await this.runJob(name, { args: a.values, docs, settings: this.state.settings, secrets, tokens, spec: jobSpec(this.m, name), reason });
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
