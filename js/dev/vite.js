// The Vite plugin for a Slowboard app UI:
//
//   import { slowboard } from "@slowboard/dev/vite";
//   export default { plugins: [react(), slowboard({ job: ["python3", "-m", "moon"] })] };
//
// - build: one self-contained index.html (JS, CSS, fonts and images inlined; vite-plugin-
//   singlefile), refused over the hub's 2 MB cap. The app's Dockerfile copies it to the
//   manifest's [ui] entry (usually /ui/index.html).
// - dev: the dev chrome at /__slowboard/ frames the app in the hub's sandbox and answers the
//   bridge from a mock hub (hub.js) that keeps docs and settings in .slowapp/dev.json (secrets
//   only in memory, until the server stops). Jobs run for real when `job` names the app's command (it gets
//   `job <name>`, SLOWAPP_IN/OUT/STATE/SECRETS on temp dirs, /in/args.json and /in/docs), or
//   through slowapp.dev.js (`export const jobs = {name: async ({args, docs, settings}) =>
//   ({result, docs})}`), or not at all. Contract 6: each job gets only its own secrets (an oauth
//   one as a dev token file), render has no network, and a sync job's /out/artifacts is kept in
//   .slowapp/artifacts and handed to the next render as /in/artifacts. An oauth sign-in is faked:
//   secrets.connect opens /__slowboard/connect/<name>, which connects dev@example.com.

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { parse as parseToml } from "smol-toml";
import { viteSingleFile } from "vite-plugin-singlefile";

import { HubError, MockHub, jobSpec } from "./hub.js";

export const MAX_BUNDLE = 2 * 1024 * 1024;
const HERE = path.dirname(fileURLToPath(import.meta.url));

/** slowapp.toml in `start` or the nearest directory above it. */
export function findManifest(start) {
  for (let d = path.resolve(start); ; d = path.dirname(d)) {
    const f = path.join(d, "slowapp.toml");
    if (fs.existsSync(f)) return f;
    if (path.dirname(d) === d) return null;
  }
}

function chromeHtml() {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>slowapp dev</title>
<style>
  * { box-sizing: border-box; } [hidden] { display: none !important; }
  body { margin: 0; background: var(--paper); color: var(--text); font: 15px/1.4 system-ui, sans-serif; }
  header { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; padding: 10px 16px; border-bottom: 3px solid var(--keyline); }
  header b { font: 700 13px/1 ui-monospace, monospace; letter-spacing: .1em; text-transform: uppercase; }
  button { font: inherit; background: var(--paper); color: var(--text); border: 2px solid var(--keyline); padding: 4px 10px; cursor: pointer; }
  main { max-width: 1080px; margin: 0 auto; padding: 16px; display: grid; gap: 12px; }
  body[data-width="phone"] main { max-width: 422px; }
  .head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px; }
  h1 { margin: 0; font-size: 1.6rem; } .muted { color: var(--muted); font-size: .9rem; }
  .chip { background: var(--ink-yellow); color: #111; border: 2px solid var(--keyline); padding: 2px 6px; font-size: .8rem; text-transform: uppercase; }
  iframe { display: block; width: 100%; height: 70vh; min-height: 320px; border: 3px solid var(--keyline); background: var(--paper); box-shadow: 6px 6px 0 var(--keyline); }
  #toast { border: 2px solid var(--keyline); padding: 8px 12px; background: var(--wash); } #toast[data-tone=bad] { border-color: var(--ink-red); }
  dialog { border: 3px solid var(--keyline); background: var(--paper); color: var(--text); padding: 20px; box-shadow: 6px 6px 0 var(--keyline); }
  details { font: 12px/1.4 ui-monospace, monospace; } #log { list-style: none; padding: 0; margin: 8px 0 0; max-height: 240px; overflow: auto; }
</style></head>
<body data-width="full">
<header><b>slowapp dev</b><span class="muted">a stand-in for the hub's app page: same sandbox, same bridge, a mock hub</span>
  <span style="flex:1"></span><button id="width" type="button">Width: full</button><button id="theme" type="button">Theme</button><button id="reload" type="button">Reload app</button></header>
<main>
  <p id="toast" role="status" hidden></p>
  <div class="head"><h1 id="title">App</h1><span class="muted" id="sub"></span><span class="chip" id="run" hidden></span></div>
  <iframe id="frame" title="The app" sandbox="allow-scripts allow-forms" referrerpolicy="no-referrer"></iframe>
  <details><summary>Bridge log</summary><ul id="log"></ul></details>
</main>
<dialog id="ask"><form method="dialog"><p id="ask-text"></p><button value="ok">OK</button> <button value="cancel">Cancel</button></form></dialog>
<script type="module" src="/__slowboard/chrome.js"></script>
</body></html>`;
}

/**
 * Whether a request comes from this server's own pages (the chrome). The mock hub's endpoints run
 * jobs with dev secrets and hand out docs, so another site, or a sandboxed frame on one
 * (`Origin: null`), must not reach them; curl and the like send neither header.
 */
export function sameOrigin(req) {
  const site = req.headers["sec-fetch-site"];
  if (site && site !== "same-origin" && site !== "none") return false; // none: typed in the address bar
  const origin = req.headers.origin;
  return !origin || origin === `http://${req.headers.host}` || origin === `https://${req.headers.host}`;
}

function readJson(f, fallback) {
  try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return fallback; }
}

/** /run/secrets as a job sees it: values as <name>, oauth tokens as <name>.json or <name>/<account>.json. */
export function writeSecrets(dir, secrets = {}, tokens = {}) {
  for (const [n, v] of Object.entries(secrets)) if (v != null) fs.writeFileSync(path.join(dir, n), v, { mode: 0o600 });
  for (const [n, tok] of Object.entries(tokens)) {
    if (Array.isArray(tok)) {
      fs.mkdirSync(path.join(dir, n));
      for (const { account, ...t } of tok) fs.writeFileSync(path.join(dir, n, `${account}.json`), JSON.stringify(t), { mode: 0o600 });
    } else fs.writeFileSync(path.join(dir, `${n}.json`), JSON.stringify(tok), { mode: 0o600 });
  }
}

/** A sync run's /out/artifacts replaces each artifact it wrote, whole, in `keep`. */
export function keepArtifacts(out, keep) {
  const src = path.join(out, "artifacts");
  if (!fs.existsSync(src)) return [];
  const names = fs.readdirSync(src).filter((n) => fs.statSync(path.join(src, n)).isDirectory());
  for (const n of names) {
    fs.rmSync(path.join(keep, n), { recursive: true, force: true });
    fs.cpSync(path.join(src, n), path.join(keep, n), { recursive: true });
  }
  return names;
}

/**
 * Run one job as the hub would (contract 4 paths, on temp dirs): the app's command on this
 * machine (`cmd`), or its image under docker/podman (`image`, mounted like the hub's §8.3:
 * /in ro, /out, /data, /run/secrets ro; no network unless the job may have it, jobSpec).
 */
export function commandRunner({ cmd, image, engine = "docker", cwd, manifestPath, manifest, env = {}, stateDir, artifactsDir }) {
  artifactsDir ||= path.join(path.dirname(stateDir), "artifacts");
  return (name, { args, docs, settings, secrets, tokens, spec, reason }) => new Promise((resolve) => {
    spec ||= jobSpec(manifest, name);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "slowapp-dev-"));
    const [inp, out, sec] = ["in", "out", "secrets"].map((d) => path.join(tmp, d));
    fs.mkdirSync(path.join(inp, "docs"), { recursive: true });
    fs.mkdirSync(out);
    fs.mkdirSync(sec);
    fs.mkdirSync(stateDir, { recursive: true });
    fs.writeFileSync(path.join(inp, "args.json"), JSON.stringify(args || {}));
    fs.writeFileSync(path.join(inp, "settings.json"), JSON.stringify(settings || {}));
    for (const [n, v] of Object.entries(docs || {})) fs.writeFileSync(path.join(inp, "docs", `${n}.json`), JSON.stringify(v));
    writeSecrets(sec, secrets, tokens);
    if (spec.kind === "render" && fs.existsSync(artifactsDir)) fs.cpSync(artifactsDir, path.join(inp, "artifacts"), { recursive: true });
    const run = {
      SLOWAPP_CONTRACT: String(manifest.app?.contract ?? 4), SLOWAPP_APP: manifest.app?.id || "app",
      SLOWAPP_JOB: name, SLOWAPP_RUN_ID: `r_dev_${Date.now()}`, SLOWAPP_REASON: reason || "manual",
      SLOWAPP_MODE: "live", SLOWAPP_FEEDS: "[]", TZ: process.env.TZ || "America/Vancouver",
    };
    let argv, opts;
    if (image) {
      fs.chmodSync(out, 0o777);
      fs.chmodSync(stateDir, 0o777); // /data, as /out: the image's user isn't this one
      const net = spec.network === "egress" ? [] : ["--network", "none"];
      argv = [engine, "run", "--rm", "--read-only", "--tmpfs", "/tmp", ...net,
        "-v", `${inp}:/in:ro`, "-v", `${out}:/out`, "-v", `${path.resolve(stateDir)}:/data`, "-v", `${sec}:/run/secrets:ro`,
        ...Object.entries({ ...run, ...env, SLOWAPP_STATE: "/data" }).flatMap(([k, v]) => ["-e", `${k}=${v}`]),
        image, "job", name];
      opts = { cwd };
    } else {
      argv = [...cmd, "job", name];
      opts = {
        cwd,
        env: { ...process.env, ...env, ...run, SLOWAPP_IN: inp, SLOWAPP_OUT: out, SLOWAPP_STATE: stateDir, SLOWAPP_SECRETS: sec, SLOWAPP_MANIFEST: manifestPath },
      };
    }
    const child = spawn(argv[0], argv.slice(1), { ...opts, stdio: ["ignore", "pipe", "pipe"] });
    let log = "";
    const keep = (b) => { log = (log + b).slice(-8192); };
    child.stdout.on("data", keep);
    child.stderr.on("data", keep);
    child.on("error", (e) => keep(String(e)));
    child.on("close", (code) => {
      const outDocs = {};
      for (const f of fs.existsSync(path.join(out, "docs")) ? fs.readdirSync(path.join(out, "docs")) : []) {
        if (f.endsWith(".json")) outDocs[f.slice(0, -5)] = readJson(path.join(out, "docs", f), null);
      }
      const result = readJson(path.join(out, "result.json"), null);
      const feeds = fs.existsSync(path.join(out, "feeds")) && fs.readdirSync(path.join(out, "feeds")).length > 0;
      if (code === 0 && spec.kind !== "render") keepArtifacts(out, artifactsDir);
      fs.rmSync(tmp, { recursive: true, force: true });
      if (log.trim()) process.stderr.write(`[slowapp dev] ${name}: ${log.trim()}\n`);
      resolve({ exit: code ?? 1, result, docs: outDocs, log, feeds });
    });
  });
}

/**
 * @param {object} [opts]
 * @param {string} [opts.manifest]  path to slowapp.toml (default: the nearest one above the Vite root)
 * @param {string[]} [opts.job]     the app's command, run as `<job...> job <name>` (e.g. ["python3", "-m", "moon"])
 * @param {string} [opts.image]     or the app's image, run under `opts.engine` (docker, or podman) as the hub runs it
 * @param {Record<string,string>} [opts.env]  extra environment for jobs (e.g. PYTHONPATH)
 * @param {number} [opts.maxBytes]  the bundle cap (the hub's: 2 MB)
 */
export function slowboard(opts = {}) {
  let root = process.cwd();
  const plugin = {
    name: "slowboard",
    config(config) {
      return {
        base: "./",
        build: {
          assetsInlineLimit: () => true,
          cssCodeSplit: false,
          modulePreload: false,
          ...(config.build || {}),
        },
      };
    },
    configResolved(c) { root = c.root; },

    configureServer(server) {
      const manifestPath = opts.manifest ? path.resolve(root, opts.manifest) : findManifest(root);
      if (!manifestPath) throw new Error("slowapp dev: no slowapp.toml above " + root);
      const appDir = path.dirname(manifestPath);
      const devDir = path.join(appDir, ".slowapp");
      const stateFile = path.join(devDir, "dev.json");
      const manifest = parseToml(fs.readFileSync(manifestPath, "utf8"));
      const clients = new Set();
      const emit = (m) => { for (const res of clients) res.write(`data: ${JSON.stringify(m)}\n\n`); };
      let runJob;
      if (opts.image || opts.job) {
        runJob = commandRunner({ cmd: opts.job, image: opts.image, engine: opts.engine, cwd: appDir, manifestPath, manifest, env: opts.env, stateDir: path.join(devDir, "data") });
      } else if (fs.existsSync(path.join(appDir, "slowapp.dev.js"))) {
        const mod = import(pathToFileURL(path.join(appDir, "slowapp.dev.js")).href);
        runJob = async (name, ctx) => {
          const f = (await mod).jobs?.[name];
          if (!f) return { exit: 0, result: null, log: `slowapp.dev.js has no job ${name}` };
          const r = (await f(ctx)) || {};
          return { exit: r.exit ?? 0, result: r.result ?? null, docs: r.docs, log: r.log || "" };
        };
      }
      const hub = new MockHub({
        manifest, state: { ...readJson(stateFile, {}), secrets: [] }, runJob, emit,
        save: () => {
          fs.mkdirSync(devDir, { recursive: true });
          const { docs, settings } = hub.state;
          fs.writeFileSync(stateFile, JSON.stringify({ docs, settings }, null, 2));
        },
      });

      server.middlewares.use((req, res, next) => {
        const url = (req.url || "").split("?")[0];
        if (!url.startsWith("/__slowboard/")) {
          // The sandboxed frame is an opaque origin: its module and asset requests say
          // `Origin: null` and need CORS, as the hub's single file never does.
          if (req.headers.origin === "null") res.setHeader("Access-Control-Allow-Origin", "*");
          return next();
        }
        if (url === "/__slowboard/" && req.method === "GET") {
          res.setHeader("content-type", "text/html; charset=utf-8");
          return res.end(chromeHtml());
        }
        if (url === "/__slowboard/chrome.js") {
          res.setHeader("content-type", "text/javascript; charset=utf-8");
          return res.end(fs.readFileSync(path.join(HERE, "chrome.js")));
        }
        if (!sameOrigin(req)) { res.statusCode = 403; return res.end(); }
        if (url === "/__slowboard/events") {
          res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
          res.write(": hello\n\n");
          clients.add(res);
          req.on("close", () => clients.delete(res));
          return;
        }
        if (url === "/__slowboard/preview.png") {
          const f = path.join(devDir, "preview.png");
          if (!fs.existsSync(f)) { res.statusCode = 404; return res.end(); }
          res.setHeader("content-type", "image/png");
          return res.end(fs.readFileSync(f));
        }
        // The faked provider: a sign-in the chrome opened for secrets.connect.
        const signIn = url.match(/^\/__slowboard\/connect\/([^/]+)$/);
        if (signIn && req.method === "GET") {
          const name = decodeURIComponent(signIn[1]);
          const account = new URL(req.url, "http://x").searchParams.get("account") || undefined;
          res.setHeader("content-type", "text/html; charset=utf-8");
          try {
            const s = hub.completeConnect(name, account);
            const esc = (v) => String(v).replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);
            return res.end(`<!doctype html><meta charset="utf-8"><title>Connected</title><p>slowapp dev: <b>${esc(name)}</b> is connected as ${esc(s.accounts.at(-1)?.account)} (faked: no provider was asked). You can close this tab.</p>`);
          } catch (e) {
            res.statusCode = 400;
            return res.end(String(e.message).replace(/[&<>"]/g, ""));
          }
        }
        if (url === "/__slowboard/call" && req.method === "POST") {
          let body = "";
          req.on("data", (c) => { body += c; });
          req.on("end", async () => {
            res.setHeader("content-type", "application/json");
            try {
              const { call, args } = JSON.parse(body || "{}");
              res.end(JSON.stringify({ ok: true, value: await hub.handle(call, args) }));
            } catch (e) {
              const err = e instanceof HubError ? { code: e.code, message: e.message, ...e.extra() } : { code: "failed", message: String(e?.message || e) };
              res.end(JSON.stringify({ ok: false, error: err }));
            }
          });
          return;
        }
        res.statusCode = 404;
        res.end();
      });

      const print = server.printUrls?.bind(server);
      server.printUrls = () => {
        print?.();
        const u = server.resolvedUrls?.local?.[0] || "http://localhost:5173/";
        server.config.logger.info(`  ➜  Slowboard: ${u.replace(/\/$/, "")}/__slowboard/   (${manifest.app?.title || manifest.app?.id}, mock hub in ${path.relative(process.cwd(), stateFile)})`);
      };
    },

    // After vite-plugin-singlefile's (enforce: "post") has inlined everything into the HTML.
    generateBundle: {
      order: "post",
      handler(_o, bundle) {
        const max = opts.maxBytes ?? MAX_BUNDLE;
        for (const f of Object.values(bundle)) {
          const size = f.type === "asset" ? Buffer.byteLength(f.source) : Buffer.byteLength(f.code || "");
          if (f.fileName.endsWith(".html") && size > max) {
            this.error(`${f.fileName} is ${size} bytes; the hub serves at most ${max} (2 MB)`);
          }
        }
      },
    },
  };
  return [viteSingleFile({ removeViteModuleLoader: true }), plugin];
}

export default slowboard;
