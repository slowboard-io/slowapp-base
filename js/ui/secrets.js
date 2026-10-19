// @slowboard/ui/secrets: taking secrets in, as two custom elements (bridge protocol 2).
//
//   import { connect } from "@slowboard/app";
//   import { setApp } from "@slowboard/ui/secrets";     // defines the elements
//   setApp(await connect());
//
//   <sb-secret-field name="ai_key"></sb-secret-field>    a value: masked input, Save, set or not
//                                                         set (and when it was last used), Replace, Clear
//   <sb-connect name="google"></sb-connect>              an oauth sign-in: Connect, or Connected with
//                                                         the scopes, the date and the accounts, Disconnect
//
// The value typed in goes straight to the hub (secrets.set) and is never kept or shown again; the
// elements only ever know whether a secret is set. Each element uses the app given to setApp(), or
// its own `app` property. Framework-free: shadow DOM with one constructed stylesheet, no inline
// script or style, no eval, no network, so it runs under the hub's CSP as @slowboard/elements
// does. Colours and fonts come from the host's tokens (tokens.css, or app.applyTheme()).
//
// Events (bubble, composed): `sb-secret` {name, status} after a change the element made, and
// `sb-connect-url` {name, url} when a sign-in started (url: the hub's link that starts it again).

export const css = String.raw`
:host {
  --_paper: var(--paper, #ffffff); --_text: var(--text, #111111); --_keyline: var(--keyline, #111111);
  --_muted: var(--muted, #4a4a4a); --_red: var(--ink-red, #e10600); --_yellow: var(--ink-yellow, #ffde00);
  --_black: var(--ink-black, #111111); --_solid: var(--solid, #111111); --_on-solid: var(--on-solid, #ffffff);
  --_button: var(--font-button, "Silkscreen", "Courier New", monospace);
  --_code: var(--font-code, "VT323", ui-monospace, monospace);
  --_thin: var(--line-thin, 2px);
  display: block; color: var(--_text); font: inherit;
}
:host([hidden]) { display: none; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
.box { display: grid; gap: 8px; min-width: 0; }
.head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; }
label, .name { font: 0.85rem/1.2 var(--_button); }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
input { flex: 1 1 12em; min-width: 0; font: inherit; color: var(--_text); background: var(--_paper);
  border: var(--_thin) solid var(--_keyline); border-radius: 0; padding: 7px 10px; }
button { font: 0.9rem/1.2 var(--_button); padding: 8px 12px; border: var(--_thin) solid var(--_keyline);
  background: var(--_paper); color: var(--_text); border-radius: 0; cursor: pointer; }
button.solid { background: var(--_solid); color: var(--_on-solid); }
button.quiet { border-color: transparent; text-decoration: underline; text-underline-offset: 3px; padding-inline: 4px; }
button:disabled { opacity: 0.5; cursor: default; }
:focus-visible { outline: 3px solid var(--mark, var(--_yellow)); outline-offset: 2px; }
.chip { font: 1.05rem/1 var(--_code); border: var(--_thin) solid var(--_keyline); padding: 2px 8px; white-space: nowrap; }
.chip[data-on] { background: var(--_yellow); color: var(--_black); border-color: var(--_black); }
.hint { color: var(--_muted); font-size: 0.9em; margin: 0; }
.error { color: var(--_red); font-size: 0.9em; margin: 0; }
ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
li { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; min-width: 0; }
li > span { overflow-wrap: anywhere; min-width: 0; }
.scopes { font: 1.05rem/1.2 var(--_code); color: var(--_muted); overflow-wrap: anywhere; margin: 0; }
a { color: inherit; }
`;

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

/** "just now", "5 min ago", "3 h ago", "2 d ago", or a date past a month. */
export function ago(iso, now = new Date()) {
  if (!iso) return "";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  const s = Math.max(0, (now.getTime() - t.getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 30 * 86400) return `${Math.floor(s / 86400)} d ago`;
  return `on ${day(iso)}`;
}

/** 19 Oct 2026 (UTC, so it reads the same everywhere). */
export function day(iso) {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  const m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][t.getUTCMonth()];
  return `${t.getUTCDate()} ${m} ${t.getUTCFullYear()}`;
}

/** A scope as people read it: the last part of a URL scope (calendar.readonly), as it is otherwise. */
export const scopeName = (s) => String(s).replace(/^https?:\/\/[^ ]*\/auth\//, "");

/**
 * <sb-secret-field>'s HTML. m: {name, label, help, set, last_used, editing, busy, error, now}.
 * The input is empty whenever it renders: a value is never put back into the page.
 */
export function renderSecretField(m) {
  const label = m.label || m.name;
  const chip = m.set
    ? `<span class="chip" data-on part="chip">Set${m.last_used ? ` · used ${esc(ago(m.last_used, m.now))}` : ""}</span>`
    : `<span class="chip" part="chip">Not set</span>`;
  const dis = m.busy ? " disabled" : "";
  const entry = !m.set || m.editing
    ? `<div class="row"><input id="value" type="password" autocomplete="off" spellcheck="false" autocapitalize="off" part="input" aria-describedby="help"${dis}>`
      + `<button type="button" class="solid" data-act="save" part="button"${dis}>Save</button>`
      + (m.set ? `<button type="button" class="quiet" data-act="cancel" part="button"${dis}>Cancel</button>` : "") + `</div>`
    : `<div class="row"><button type="button" data-act="replace" part="button"${dis}>Replace</button>`
      + `<button type="button" data-act="clear" part="button"${dis}>Clear</button></div>`;
  return `<div class="box" part="box"><div class="head"><label for="value">${esc(label)}</label>${chip}</div>${entry}`
    + (m.help ? `<p class="hint" id="help">${esc(m.help)}</p>` : "")
    + (m.error ? `<p class="error" role="alert">${esc(m.error)}</p>` : "") + `</div>`;
}

/**
 * <sb-connect>'s HTML. m: {name, label, set, multiple, scopes, granted_at, accounts, busy, error,
 * url, now}.
 */
export function renderConnect(m) {
  const label = m.label || m.name;
  const dis = m.busy ? " disabled" : "";
  const accounts = m.accounts || [];
  let body;
  if (!m.set) {
    body = `<div class="head"><span class="name">${esc(label)}</span><span class="chip" part="chip">Not connected</span></div>`
      + `<div class="row"><button type="button" class="solid" data-act="connect" part="button"${dis}>Connect ${esc(label)}</button></div>`;
  } else {
    const since = m.granted_at ? ` · ${esc(day(m.granted_at))}` : "";
    body = `<div class="head"><span class="name">${esc(label)}</span><span class="chip" data-on part="chip">Connected${since}</span></div>`
      + ((m.scopes || []).length ? `<p class="scopes" part="scopes">${m.scopes.map((s) => esc(scopeName(s))).join(", ")}</p>` : "");
    if (m.multiple) {
      body += `<ul part="accounts">${accounts.map((a) => `<li><span>${esc(a.account)}${a.last_used ? ` <span class="hint">· used ${esc(ago(a.last_used, m.now))}</span>` : ""}</span>`
        + `<button type="button" class="quiet" data-act="disconnect" data-account="${esc(a.account)}" part="button"${dis}>Disconnect</button></li>`).join("")}</ul>`
        + `<div class="row"><button type="button" data-act="connect" part="button"${dis}>Add an account</button></div>`;
    } else {
      body += (accounts[0] ? `<p class="hint">${esc(accounts[0].account)}${accounts[0].last_used ? ` · used ${esc(ago(accounts[0].last_used, m.now))}` : ""}</p>` : "")
        + `<div class="row"><button type="button" data-act="disconnect" part="button"${dis}>Disconnect</button></div>`;
    }
  }
  if (m.url) body += `<p class="hint">Signing in in another window. Nothing opened? <a href="${esc(m.url)}" target="_blank" rel="noopener">Open the sign-in</a>.</p>`;
  if (m.error) body += `<p class="error" role="alert">${esc(m.error)}</p>`;
  return `<div class="box" part="box">${body}</div>`;
}

// ------------------------------------------------------------------ the elements

let defaultApp = null;
const live = new Set();

/** The app every element uses unless it has its own `app` property. Re-renders the ones on the page. */
export function setApp(app) {
  defaultApp = app;
  for (const el of live) el._attach();
}

let shared = null;
function stylesheet() {
  if (!shared && typeof CSSStyleSheet === "function" && "replaceSync" in CSSStyleSheet.prototype) {
    shared = new CSSStyleSheet();
    shared.replaceSync(css);
  }
  return shared;
}

const HTMLElementBase = globalThis.HTMLElement ?? class {};

class SecretElement extends HTMLElementBase {
  static get observedAttributes() { return ["name", "label"]; }

  constructor() {
    super();
    this._state = { busy: false, error: null, editing: false, url: null };
    this._status = null;
    this._app = null;
    this._unwatch = null;
  }

  get app() { return this._app || defaultApp; }
  set app(a) { this._app = a; if (this.isConnected) this._attach(); }

  /** The secret's status entry from the hub (null until there is an app). */
  get status() { return this._status; }

  connectedCallback() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      const sheet = stylesheet();
      if (sheet) this.shadowRoot.adoptedStyleSheets = [sheet];
      this.shadowRoot.addEventListener("click", (e) => this._click(e));
      this.shadowRoot.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && e.target?.id === "value") { e.preventDefault(); this._act("save"); }
      });
    }
    live.add(this);
    this._attach();
  }

  disconnectedCallback() {
    live.delete(this);
    this._unwatch?.();
    this._unwatch = null;
  }

  attributeChangedCallback() { if (this.isConnected) this._attach(); }

  _attach() {
    this._unwatch?.();
    this._unwatch = null;
    const app = this.app;
    const name = this.getAttribute("name");
    this._status = (app?.info?.secrets || []).find((s) => s.name === name) || null;
    if (app?.secrets?.watch) {
      this._unwatch = app.secrets.watch((ev) => {
        if (ev.name !== this.getAttribute("name")) return;
        const { event, ...s } = ev;
        this._status = s;
        this._state.url = null;
        this.render();
      });
    }
    this.render();
    if (app?.secrets) this._refresh();
  }

  async _refresh() {
    try {
      const all = await this.app.secrets.status();
      this._status = all.find((s) => s.name === this.getAttribute("name")) || null;
    } catch (e) {
      this._state.error = e.message;
    }
    this.render();
  }

  model() {
    const s = this._status || {};
    return { ...s, ...this._state, name: this.getAttribute("name"), label: this.getAttribute("label") || s.label, now: new Date() };
  }

  render() {
    if (!this.shadowRoot) return;
    if (!this.app || !this.getAttribute("name")) {
      this.shadowRoot.innerHTML = `<p class="hint">${this.getAttribute("name") ? "Not connected to the hub." : "No secret named."}</p>`;
      return;
    }
    if (!this._status) {
      this.shadowRoot.innerHTML = `<p class="error" role="alert">This app has no secret called ${esc(this.getAttribute("name"))}.</p>`;
      return;
    }
    this.shadowRoot.innerHTML = this.html(this.model());
  }

  _click(e) {
    const b = e.target?.closest?.("[data-act]");
    if (b && !b.disabled) this._act(b.dataset.act, b.dataset.account);
  }

  async _run(f) {
    this._state = { ...this._state, busy: true, error: null };
    this.render();
    try {
      await f();
      await this._refresh();
      this.dispatchEvent(new CustomEvent("sb-secret", { bubbles: true, composed: true, detail: { name: this.getAttribute("name"), status: this._status } }));
    } catch (e) {
      this._state.error = e.code === "unknown_call" ? "This hub can't do that yet." : (e.message || String(e));
    } finally {
      this._state.busy = false;
      this.render();
    }
  }

  async _confirm(text) {
    try { return this.app.ui?.confirm ? await this.app.ui.confirm(text) : true; } catch { return false; }
  }
}

/** <sb-secret-field name>: a value secret. */
export class SbSecretField extends SecretElement {
  html(m) { return renderSecretField(m); }

  async _act(act) {
    const name = this.getAttribute("name");
    if (act === "replace" || act === "cancel") {
      this._state = { ...this._state, editing: act === "replace", error: null };
      this.render();
      if (act === "replace") this.shadowRoot.getElementById("value")?.focus();
      return;
    }
    if (act === "save") {
      const input = this.shadowRoot.getElementById("value");
      const value = input?.value ?? "";
      if (input) input.value = "";
      if (!value.trim()) { this._state.error = "Type the value first."; this.render(); return; }
      await this._run(async () => { await this.app.secrets.set(name, value); this._state.editing = false; });
      return;
    }
    if (act === "clear") {
      const label = this.getAttribute("label") || this._status?.label || name;
      if (!(await this._confirm(`Clear ${label}? Jobs that need it stop until it's set again.`))) return;
      await this._run(() => this.app.secrets.clear(name));
    }
  }
}

/** <sb-connect name>: an oauth sign-in. */
export class SbConnect extends SecretElement {
  html(m) { return renderConnect(m); }

  async _act(act, account) {
    const name = this.getAttribute("name");
    if (act === "connect") {
      await this._run(async () => {
        const r = await this.app.secrets.connect(name);
        this._state.url = r?.url || null;
        if (r?.url) this.dispatchEvent(new CustomEvent("sb-connect-url", { bubbles: true, composed: true, detail: { name, url: r.url } }));
      });
      return;
    }
    if (act === "disconnect") {
      const label = this.getAttribute("label") || this._status?.label || name;
      if (!(await this._confirm(account ? `Disconnect ${account} from ${label}?` : `Disconnect ${label}?`))) return;
      await this._run(() => this.app.secrets.clear(name, account));
    }
  }
}

export const ELEMENTS = { "sb-secret-field": SbSecretField, "sb-connect": SbConnect };

/** Registers the elements (idempotent). Called on import wherever customElements exists. */
export function define(registry = globalThis.customElements) {
  if (!registry) return;
  for (const [tag, cls] of Object.entries(ELEMENTS)) if (!registry.get(tag)) registry.define(tag, cls);
}

define();
