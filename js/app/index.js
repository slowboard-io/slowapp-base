// @slowboard/app: the app side of the UI bridge (protocol 2).
//
// An app's UI runs in a sandboxed frame with no network. Once the frame has loaded, the hub's
// chrome posts {slowboard: "connect", protocol: 1} with a MessagePort; every call goes over that
// port and the chrome makes it on the hub, for this app only. The handshake says 1 so protocol 1
// bundles keep connecting; this client says 2 in its connect call and `app.protocol` is what the
// chrome agreed (1 from an older hub, whose chrome then answers secrets.connect "unknown_call").
// See protocol.json.
//
//   import { connect } from "@slowboard/app";
//   const app = await connect();
//   const { rev, value } = await app.docs.get("tags");
//   await app.docs.put("tags", { ...value, work: "important" }, rev);
//   const r = await app.jobs.run("google_finish", { url });

// protocol.json, inlined (a test keeps them equal).
export const PROTOCOL = 2;
export const CALLS = Object.freeze(["connect", "docs.get", "docs.put", "docs.watch", "settings.get", "settings.set", "secrets.status", "secrets.set", "secrets.clear", "secrets.connect", "jobs.run", "events.watch", "ui.title", "ui.toast", "ui.confirm", "ui.resize", "device.preview", "backend.fetch"]);

/** A failed call: `code` is one of protocol.json's errors; a conflict carries `rev` and `value`. */
export class BridgeError extends Error {
  constructor(error = {}) {
    super(error.message || error.code || "bridge call failed");
    this.name = "BridgeError";
    Object.assign(this, error);
    this.code = error.code || "failed";
  }
}

/**
 * The app's handle on the hub, over one port. Most apps call `connect()`; tests and other hosts
 * can hand a port in directly.
 */
export function fromPort(port, { timeoutMs = 0 } = {}) {
  let seq = 0;
  const waiting = new Map();
  const handlers = new Map(); // event -> Set(fn)
  const report = (e) => setTimeout(() => { throw e; }); // off this stack, as a page error
  port.onmessage = ({ data: m }) => {
    if (!m || typeof m !== "object") return;
    if (m.event) {
      for (const f of handlers.get(m.event) || []) {
        try { f(m); } catch (e) { report(e); }
      }
      return;
    }
    const w = waiting.get(m.id);
    if (!w) return;
    waiting.delete(m.id);
    clearTimeout(w.timer);
    if (m.ok) w.ok(m.value);
    else w.no(new BridgeError(m.error));
  };
  port.start?.();

  const call = (name, ...args) => new Promise((ok, no) => {
    const id = ++seq;
    const timer = timeoutMs ? setTimeout(() => {
      waiting.delete(id);
      no(new BridgeError({ code: "timeout", message: `${name} took over ${timeoutMs} ms` }));
    }, timeoutMs) : null;
    waiting.set(id, { ok, no, timer });
    port.postMessage({ id, call: name, args });
  });
  const on = (event, f) => {
    if (!handlers.has(event)) handlers.set(event, new Set());
    handlers.get(event).add(f);
    return () => handlers.get(event).delete(f);
  };

  const docWatchers = new Map(); // name -> Set(fn)
  const docsWatched = new Set(); // names the hub was asked to watch (a refused ask is asked again)
  let runsWatched = false;
  on("doc", (m) => { for (const f of docWatchers.get(m.name) || []) f({ rev: m.rev, value: m.value, at: m.at }); });

  const app = {
    port,
    call,
    on,
    /** What the hub said at connect: {app, title, contract, tz, locale, protocol, settings_schema, settings, docs, secrets, jobs, backend, theme, tokens}. */
    info: null,
    /** The protocol the chrome agreed at connect: 2, or 1 from an older hub (no secrets.connect). */
    get protocol() { return app.info?.protocol ?? 1; },
    docs: {
      /** @returns {Promise<{rev: number, value: any, at: string|null}>} rev 0 and null when never written */
      get: (name) => call("docs.get", name),
      /** Write `value` over revision `rev` (the one you read). A stale rev throws code "conflict" with the current {rev, value}. */
      put: (name, value, rev) => call("docs.put", name, value, rev),
      /** Changes from jobs and other tabs: f({rev, value}). Returns an unsubscribe. */
      watch(name, f) {
        if (!docWatchers.has(name)) docWatchers.set(name, new Set());
        if (!docsWatched.has(name)) {
          docsWatched.add(name);
          call("docs.watch", name).catch((e) => { docsWatched.delete(name); report(e); });
        }
        docWatchers.get(name).add(f);
        return () => docWatchers.get(name).delete(f);
      },
    },
    settings: {
      get: () => call("settings.get"),
      /** Checked against the manifest's [settings]; an invalid value throws code "invalid" with `errors`. */
      set: (values) => call("settings.set", values),
    },
    secrets: {
      /**
       * Whether each is set, never its value: [{name, optional, set, kind, label, help, last_used}],
       * and for an oauth secret also {auth, multiple, scopes, granted_at, accounts}.
       */
      status: () => call("secrets.status"),
      /** A value secret. On an oauth secret: code "kind". */
      set: (name, value) => call("secrets.set", name, value),
      /** Clear a value; disconnect an oauth secret, or with `account` one of its accounts. */
      clear: (name, account) => (account == null ? call("secrets.clear", name) : call("secrets.clear", name, account)),
      /**
       * Protocol 2, an oauth secret: the hub's page starts the sign-in at top level and resolves
       * {url}, a hub link that starts it again (for a blocked pop-up). The outcome arrives as a
       * `secret` event (secrets.watch). `account` reconnects one account of a multiple secret.
       */
      connect: (name, opts) => (opts ? call("secrets.connect", name, opts) : call("secrets.connect", name)),
      /** Protocol 2: f({name, ...status}) after any set, clear, connect or disconnect. Returns an unsubscribe. */
      watch: (f) => on("secret", f),
    },
    jobs: {
      /** Run one of the app's jobs with `args` (/in/args.json); resolves when it ends: {run, outcome, ok, exit, result, message}. */
      run: (name, args = {}) => call("jobs.run", name, args),
    },
    events: {
      /** The app's runs as they start and end: f({job, run, phase: "started"|"ended", outcome}). */
      runs(f) {
        if (!runsWatched) {
          runsWatched = true;
          call("events.watch").catch((e) => { runsWatched = false; report(e); });
        }
        return on("run", f);
      },
    },
    ui: {
      title: (text) => call("ui.title", text),
      toast: (text, opts = {}) => call("ui.toast", text, opts),
      /** The hub's own dialog (confirm() doesn't work in a sandbox). Resolves true or false. */
      confirm: (text) => call("ui.confirm", text),
      resize: (height) => call("ui.resize", height),
      /** Keep the frame as tall as the document. Returns a stop function. */
      autoResize(el = globalThis.document?.documentElement) {
        if (!el || typeof ResizeObserver === "undefined") return () => {};
        let last = 0;
        const send = () => {
          const h = Math.ceil(el.scrollHeight);
          if (h !== last) { last = h; call("ui.resize", h).catch(() => {}); }
        };
        const ro = new ResizeObserver(send);
        ro.observe(el);
        send();
        return () => ro.disconnect();
      },
    },
    device: {
      /** What the panel shows now: {type: "image/png", bytes: ArrayBuffer}. */
      preview: () => call("device.preview"),
    },
    backend: {
      fetch: (path, init) => call("backend.fetch", path, init),
    },
    /** The hub's theme: f({theme: "light"|"dark", tokens}) now and on every change. */
    onTheme(f) {
      if (app.info) f({ theme: app.info.theme, tokens: app.info.tokens });
      return on("theme", (m) => { app.info = { ...app.info, theme: m.theme, tokens: m.tokens }; f(m); });
    },
    /** Apply the hub's colours as CSS custom properties and data-theme on `el`, and follow changes. */
    applyTheme(el = globalThis.document?.documentElement) {
      return app.onTheme(({ theme, tokens }) => {
        if (!el) return;
        el.dataset.theme = theme;
        for (const [k, v] of Object.entries(tokens || {})) if (v) el.style.setProperty(k, v);
      });
    },
  };
  return app;
}

/**
 * Wait for the hub's chrome to hand this frame its port, then connect. Rejects with code "no_hub"
 * after `waitMs` when the page isn't running in a Slowboard chrome (opened on its own).
 */
export function connect({ waitMs = 10000, timeoutMs = 0, win = globalThis } = {}) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      win.removeEventListener("message", onMsg);
      reject(new BridgeError({ code: "no_hub", message: "no Slowboard hub connected to this page" }));
    }, waitMs);
    async function onMsg(e) {
      const d = e.data;
      if (e.source !== win.parent || !d || d.slowboard !== "connect" || !e.ports?.[0]) return;
      win.removeEventListener("message", onMsg);
      clearTimeout(timer);
      // Any protocol from 1 on: which one is used is agreed in the connect call.
      if (!Number.isInteger(d.protocol) || d.protocol < 1) {
        reject(new BridgeError({ code: "protocol", message: `the hub's handshake says protocol ${d.protocol}` }));
        return;
      }
      const app = fromPort(e.ports[0], { timeoutMs });
      try {
        const info = await app.call("connect", { protocol: PROTOCOL });
        app.info = { ...info, protocol: Math.min(PROTOCOL, Number(info?.protocol) || 1) };
        resolve(app);
      } catch (err) { reject(err); }
    }
    win.addEventListener("message", onMsg);
  });
}
