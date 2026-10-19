// The dev chrome (`slowapp dev`): a stand-in for the hub's /apps/<id> page. It frames the app at
// "/" in the same sandbox the hub uses (allow-scripts allow-forms, no allow-same-origin), hands
// it a MessagePort on load, and answers the bridge: the hub's calls go to the mock hub in the
// dev server (POST /__slowboard/call), the chrome's own (ui.*, device.preview) are drawn here.

const LIGHT = {
  "--paper": "#ffffff", "--text": "#111111", "--keyline": "#111111", "--muted": "#4a4a4a", "--wash": "#f3f3f1",
  "--solid": "#111111", "--on-solid": "#ffffff",
};
const DARK = {
  "--paper": "#141414", "--text": "#f1f0ec", "--keyline": "#f1f0ec", "--muted": "#b3b1aa", "--wash": "#222222",
  "--solid": "#f1f0ec", "--on-solid": "#141414",
};
const SHARED = {
  "--accent": "#e10600", "--mark": "#ffde00", "--ink-black": "#111111", "--ink-white": "#ffffff",
  "--ink-yellow": "#ffde00", "--ink-red": "#e10600", "--line": "3px", "--line-thin": "2px",
};
const CHROME = ["ui.title", "ui.toast", "ui.confirm", "ui.resize", "device.preview"];

const $ = (id) => document.getElementById(id);
const frame = $("frame");
let port = null;
let theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
let width = "full";

const themeMsg = () => ({ theme, tokens: { ...(theme === "dark" ? DARK : LIGHT), ...SHARED } });
function paintChrome() {
  for (const [k, v] of Object.entries(themeMsg().tokens)) document.documentElement.style.setProperty(k, v);
  $("theme").textContent = `Theme: ${theme}`;
}

function toast(text, bad) {
  const t = $("toast");
  t.textContent = text;
  t.dataset.tone = bad ? "bad" : "";
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, bad ? 10000 : 5000);
}

function ask(text) {
  const d = $("ask");
  $("ask-text").textContent = String(text).slice(0, 500);
  d.returnValue = "";
  d.showModal();
  return new Promise((done) => d.addEventListener("close", () => done(d.returnValue === "ok"), { once: true }));
}

function log(dir, m) {
  const li = document.createElement("li");
  li.textContent = `${new Date().toLocaleTimeString()} ${dir} ${JSON.stringify(m).slice(0, 300)}`;
  $("log").prepend(li);
  while ($("log").children.length > 80) $("log").lastChild.remove();
}

async function hubCall(call, args) {
  const r = await fetch("/__slowboard/call", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ call, args }) });
  const j = await r.json();
  if (!j.ok) throw Object.assign(new Error(j.error.message), j.error);
  return j.value;
}

const chrome = {
  "ui.title": (t) => { $("sub").textContent = String(t ?? "").slice(0, 80); return true; },
  "ui.toast": (t, o) => { toast(String(t).slice(0, 300), o?.tone === "bad"); return true; },
  "ui.confirm": (t) => ask(t),
  "ui.resize": (h) => { const e = frame.offsetHeight - frame.clientHeight; frame.style.height = `${Math.max(160, Math.min(6000, Number(h) || 0)) + e}px`; return true; },
  async "device.preview"() {
    const r = await fetch("/__slowboard/preview.png", { cache: "no-store" });
    if (!r.ok) throw Object.assign(new Error("no .slowapp/preview.png in this project"), { code: "not_found" });
    return { type: "image/png", bytes: await r.arrayBuffer() };
  },
};

async function answer(p, m) {
  if (!m || typeof m.call !== "string") return;
  log("→", { call: m.call, args: m.args });
  const reply = (r, transfer = []) => { if (p === port) { p.postMessage({ id: m.id, ...r }, transfer); log("←", r.ok ? { ok: true } : r); } };
  try {
    let value;
    if (CHROME.includes(m.call)) value = await chrome[m.call](...(m.args || []));
    else value = await hubCall(m.call, m.args || []);
    // The protocol both speak: the app says its own in connect's argument (protocol 1 apps don't).
    if (m.call === "connect") value = { ...value, ...themeMsg(), locale: navigator.language, protocol: Math.min(2, Number(m.args?.[0]?.protocol) || 1) };
    // An oauth sign-in starts at top level, from the chrome; the frame gets only the hub's link.
    if (m.call === "secrets.connect" && value?.url) window.open(value.url, "_blank", "noopener");
    if (m.call === "jobs.run") $("run").hidden = true;
    reply({ ok: true, value }, value?.bytes instanceof ArrayBuffer ? [value.bytes] : []);
  } catch (e) {
    const { message, code, ...rest } = e;
    reply({ ok: false, error: { code: code || "failed", message, ...rest } });
  }
}

frame.addEventListener("load", () => {
  if (port) port.close();
  const ch = new MessageChannel();
  port = ch.port1;
  const p = port;
  p.onmessage = (e) => answer(p, e.data);
  frame.contentWindow.postMessage({ slowboard: "connect", protocol: 1 }, "*", [ch.port2]);
});

// The mock hub's pushes: doc changes (a job's write, another tab) and runs.
const es = new EventSource("/__slowboard/events");
es.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.event === "run") { $("run").hidden = m.phase !== "started"; $("run").textContent = `Running ${m.job}`; }
  if (port) port.postMessage(m);
  log("⇠", m);
};

$("theme").onclick = () => { theme = theme === "dark" ? "light" : "dark"; paintChrome(); if (port) port.postMessage({ event: "theme", ...themeMsg() }); };
$("width").onclick = () => {
  width = width === "full" ? "phone" : "full";
  document.body.dataset.width = width;
  $("width").textContent = width === "phone" ? "Width: phone (390)" : "Width: full";
};
$("reload").onclick = () => { frame.src = "/"; };

paintChrome();
fetch("/__slowboard/call", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ call: "connect", args: [] }) })
  .then((r) => r.json()).then((j) => { if (j.ok) { $("title").textContent = j.value.title; document.title = `${j.value.title} · slowapp dev`; } });
frame.src = "/";
