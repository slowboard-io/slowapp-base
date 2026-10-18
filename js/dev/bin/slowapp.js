#!/usr/bin/env node
// slowapp dev | build | check [file]
//   dev    Vite's dev server with the Slowboard chrome at /__slowboard/ (the slowboard() plugin
//          must be in vite.config)
//   build  vite build: dist/index.html, one self-contained file
//   check  the built file against the hub's cap (default dist/index.html)
import { spawn } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const [cmd = "dev", ...rest] = process.argv.slice(2);
const MAX = 2 * 1024 * 1024;

function vite(args) {
  const req = createRequire(path.join(process.cwd(), "package.json"));
  const bin = path.join(path.dirname(req.resolve("vite/package.json")), "bin", "vite.js");
  const c = spawn(process.execPath, [bin, ...args], { stdio: "inherit" });
  c.on("exit", (code) => process.exit(code ?? 1));
}

if (cmd === "dev") vite(rest);
else if (cmd === "build") vite(["build", ...rest]);
else if (cmd === "check") {
  const f = rest[0] || "dist/index.html";
  const size = fs.statSync(f).size;
  const html = fs.readFileSync(f, "utf8");
  const external = [...html.matchAll(/<(?:script|link|img)\b[^>]*\b(?:src|href)="(?!data:|#)([^"]+)"/g)].map((m) => m[1]);
  console.log(`${f}: ${size} bytes (cap ${MAX})`);
  if (external.length) console.error(`  loads files the sandbox can't fetch: ${external.join(", ")}`);
  process.exit(size > MAX || external.length ? 1 : 0);
} else {
  console.error("usage: slowapp dev | build | check [file]");
  process.exit(2);
}
