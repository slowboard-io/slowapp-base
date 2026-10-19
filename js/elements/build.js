// Builds dist/: slowboard-elements.js (one ES module, not minified, so a vendored copy reads and
// diffs) and elements.css (the same stylesheet, for a server-rendered <link>). The module's first
// line names the version and the sha256 of the rest, so a copy can be checked without this repo:
//
//   /*! @slowboard/elements 0.1.0 sha256:<hex of everything after this line> */
//
// The hub vendors dist/slowboard-elements.js into crates/slowhub/web/; slowboard.io vendors dist/.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "vite";

import { css } from "./styles.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(fs.readFileSync(path.join(here, "package.json"), "utf8"));

export const header = (body) =>
  `/*! ${pkg.name} ${pkg.version} sha256:${crypto.createHash("sha256").update(body).digest("hex")} */\n`;

/** Builds into `out` (default dist/) and returns the paths. */
export async function buildElements(out = path.join(here, "dist")) {
  const tmp = fs.mkdtempSync(path.join(out + "-tmp-"));
  try {
    await build({
      configFile: false, logLevel: "silent", root: here,
      build: {
        outDir: tmp, emptyOutDir: true, minify: false, target: "es2022", copyPublicDir: false,
        lib: { entry: path.join(here, "index.js"), formats: ["es"], fileName: () => "slowboard-elements.js" },
      },
    });
    const body = fs.readFileSync(path.join(tmp, "slowboard-elements.js"), "utf8");
    fs.mkdirSync(out, { recursive: true });
    const js = path.join(out, "slowboard-elements.js");
    const cssOut = path.join(out, "elements.css");
    fs.writeFileSync(js, header(body) + body);
    fs.writeFileSync(cssOut, `/* ${pkg.name} ${pkg.version}: the elements' stylesheet (styles.js) */\n${css.trimStart()}`);
    return { js, css: cssOut };
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const r = await buildElements(process.argv[2] ? path.resolve(process.argv[2]) : undefined);
  console.log(`${path.relative(process.cwd(), r.js)}  ${fs.statSync(r.js).size} bytes`);
  console.log(`${path.relative(process.cwd(), r.css)}  ${fs.statSync(r.css).size} bytes`);
}
