// @slowboard/ui/secrets: the HTML of <sb-secret-field> and <sb-connect> in each state, escaping,
// nothing a strict CSP refuses, and what each button does against a fake app (no DOM in Node: the
// element classes are driven with a stand-in shadow root).
import assert from "node:assert/strict";
import { test } from "node:test";

import { SbConnect, SbSecretField, ago, css, day, esc, renderConnect, renderSecretField, scopeName } from "../secrets.js";

const NOW = new Date("2026-10-19T12:00:00Z");

function assertCspClean(html) {
  assert.doesNotMatch(html, /<script/i, "no script");
  assert.doesNotMatch(html, /<style/i, "no <style>");
  const tags = html.match(/<[^>]*>/g) || [];
  assert.ok(!tags.some((t) => /\sstyle=/i.test(t)), "no style attribute");
  assert.ok(!tags.some((t) => /\son[a-z]+=/i.test(t)), "no event-handler attribute");
  assert.doesNotMatch(html, /javascript:/i, "no javascript: URL");
}

test("times and names", () => {
  assert.equal(ago("2026-10-19T11:59:30Z", NOW), "just now");
  assert.equal(ago("2026-10-19T11:15:00Z", NOW), "45 min ago");
  assert.equal(ago("2026-10-19T09:00:00Z", NOW), "3 h ago");
  assert.equal(ago("2026-10-16T12:00:00Z", NOW), "3 d ago");
  assert.equal(ago("2026-08-01T12:00:00Z", NOW), "on 1 Aug 2026");
  assert.equal(ago(null, NOW), "");
  assert.equal(day("2026-10-19T23:30:00Z"), "19 Oct 2026");
  assert.equal(scopeName("https://www.googleapis.com/auth/calendar.readonly"), "calendar.readonly");
  assert.equal(scopeName("email"), "email");
  assert.equal(esc(`<a href="x">'&`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;");
});

test("a value field: not set, set with last used, replacing, busy, an error", () => {
  let h = renderSecretField({ name: "ai_key", label: "AI key", help: "OpenAI-compatible", set: false, now: NOW });
  assert.match(h, /Not set/);
  assert.match(h, /type="password"/);
  assert.match(h, /autocomplete="off"/);
  assert.match(h, /data-act="save"/);
  assert.doesNotMatch(h, /data-act="clear"/);
  assert.match(h, /OpenAI-compatible/);
  h = renderSecretField({ name: "ai_key", set: true, last_used: "2026-10-19T09:00:00Z", now: NOW });
  assert.match(h, /Set · used 3 h ago/);
  assert.doesNotMatch(h, /<input/, "a set secret shows no input until Replace");
  assert.match(h, /data-act="replace"/);
  assert.match(h, /data-act="clear"/);
  assert.match(h, /<label for="value">ai_key<\/label>/, "the name when there's no label");
  h = renderSecretField({ name: "k", set: true, editing: true, now: NOW });
  assert.match(h, /data-act="save"/);
  assert.match(h, /data-act="cancel"/);
  assert.doesNotMatch(h, /value="/, "the input never carries a value");
  h = renderSecretField({ name: "k", set: false, busy: true, error: "<b>no</b>", now: NOW });
  assert.match(h, /disabled/);
  assert.match(h, /role="alert">&lt;b&gt;no&lt;\/b&gt;/);
  for (const m of [{ set: false }, { set: true, last_used: "x" }, { set: true, editing: true, error: "e" }]) {
    assertCspClean(renderSecretField({ name: "n", label: `"><script>`, ...m, now: NOW }));
  }
});

test("a connect: not connected, one account, several, the fallback link", () => {
  let h = renderConnect({ name: "google", label: "Google Calendar", set: false, now: NOW });
  assert.match(h, /Not connected/);
  assert.match(h, /data-act="connect"[^>]*>Connect Google Calendar</);
  const acct = (account, last_used = null) => ({ account, scopes: ["email"], granted_at: "2026-10-18T10:00:00Z", last_used });
  h = renderConnect({ name: "gh", set: true, multiple: false, scopes: ["repo", "read:user"], granted_at: "2026-10-18T10:00:00Z",
    accounts: [acct("mike", "2026-10-19T11:00:00Z")], now: NOW });
  assert.match(h, /Connected · 18 Oct 2026/);
  assert.match(h, /repo, read:user/);
  assert.match(h, /mike · used 1 h ago/);
  assert.match(h, /data-act="disconnect"[^>]*>Disconnect</);
  assert.doesNotMatch(h, /data-account/);
  h = renderConnect({ name: "google", set: true, multiple: true, scopes: ["https://www.googleapis.com/auth/calendar.readonly"],
    accounts: [acct("a@example.com"), acct(`b"<@example.com`)], now: NOW });
  assert.match(h, /calendar\.readonly/);
  assert.match(h, /data-account="a@example.com"/);
  assert.match(h, /data-account="b&quot;&lt;@example.com"/);
  assert.match(h, /Add an account/);
  h = renderConnect({ name: "google", set: false, url: "/oauth/start?x=1&y=2", now: NOW });
  assert.match(h, /href="\/oauth\/start\?x=1&amp;y=2" target="_blank" rel="noopener"/);
  for (const m of [{ set: false, url: "/x" }, { set: true, accounts: [acct("x")] }, { set: true, multiple: true, accounts: [acct("<i>")], error: "e" }]) {
    assertCspClean(renderConnect({ name: "n", label: "<img src=x onerror=alert(1)>", ...m, now: NOW }));
  }
});

test("the stylesheet has no imports or URLs (nothing to fetch)", () => {
  assert.doesNotMatch(css, /@import|url\(/);
});

/** An element driven without a DOM: attributes, a stand-in shadow root, and a fake app. */
function drive(Cls, name, status, extra = {}) {
  const calls = [];
  const input = { value: "", focus() {} };
  const app = {
    info: { secrets: [status] },
    secrets: {
      status: async () => [status],
      set: async (...a) => { calls.push(["set", ...a]); Object.assign(status, { set: true }); return { name, set: true }; },
      clear: async (...a) => { calls.push(["clear", ...a]); return { name, set: false }; },
      connect: async (...a) => { calls.push(["connect", ...a]); return { url: "/hub/start" }; },
      watch: () => () => {},
    },
    ui: { confirm: async () => extra.confirm ?? true },
  };
  const el = new Cls();
  const attrs = { name };
  const events = [];
  el.getAttribute = (k) => attrs[k] ?? null;
  el.dispatchEvent = (e) => events.push(e);
  Object.defineProperty(el, "shadowRoot", { value: { innerHTML: "", getElementById: (id) => (id === "value" ? input : null) } });
  el.app = app;
  el._status = status;
  return { el, calls, input, events };
}

test("the field saves what was typed, empties the input, and clears after the hub's confirm", async () => {
  const { el, calls, input, events } = drive(SbSecretField, "ai_key", { name: "ai_key", optional: true, set: false, kind: "value" });
  await el._act("save");
  assert.deepEqual(calls, [], "nothing typed: nothing sent");
  assert.match(el.shadowRoot.innerHTML, /Type the value first/);
  input.value = "sk-secret";
  await el._act("save");
  assert.deepEqual(calls, [["set", "ai_key", "sk-secret"]]);
  assert.equal(input.value, "", "the input is emptied");
  assert.doesNotMatch(el.shadowRoot.innerHTML, /sk-secret/);
  assert.equal(events.at(-1).type, "sb-secret");
  await el._act("clear");
  assert.deepEqual(calls.at(-1), ["clear", "ai_key"]);

  const no = drive(SbSecretField, "k", { name: "k", set: true, kind: "value" }, { confirm: false });
  await no.el._act("clear");
  assert.deepEqual(no.calls, [], "a refused confirm clears nothing");
});

test("connect starts the sign-in and shows the hub's link; disconnect names the account", async () => {
  const { el, calls, events } = drive(SbConnect, "google", { name: "google", set: true, kind: "oauth", multiple: true,
    accounts: [{ account: "a@example.com", scopes: [] }] });
  await el._act("connect");
  assert.deepEqual(calls, [["connect", "google"]]);
  assert.match(el.shadowRoot.innerHTML, /href="\/hub\/start"/);
  assert.ok(events.some((e) => e.type === "sb-connect-url" && e.detail.url === "/hub/start"));
  await el._act("disconnect", "a@example.com");
  assert.deepEqual(calls.at(-1), ["clear", "google", "a@example.com"]);
});

test("an older hub's unknown_call reads as words", async () => {
  const { el } = drive(SbConnect, "google", { name: "google", set: false, kind: "oauth" });
  el.app.secrets.connect = async () => { throw Object.assign(new Error("no call secrets.connect"), { code: "unknown_call" }); };
  await el._act("connect");
  assert.match(el.shadowRoot.innerHTML, /This hub can&#39;t do that yet/);
});
