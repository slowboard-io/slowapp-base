"""The catalog bundle (MANIFEST.md "Catalog bundle"): everything an app's page shows, computed by CI
from the image and from renders of the app's own examples, so it can't drift from what the app
does. Three steps:

  slowapp catalog build [DIR] --image IMAGE [--out out/catalog] [--slowd-image IMG | --slowd PATH]
      Every [[example]] in fixture mode, twice (the two renders must match pixel for pixel), at its
      own surfaces and again at every standard surface each `slot` feed could be given. A feed that
      fails at a size is listed as unsupported there, with the reason, never left out. Writes
      catalog.json and screens/: every card of every example at every size that works, prompt
      question cards and each answer's rest card, and a full-panel picture per example drawn with
      slowd's own strips (`slowd compose`, from the slowd-sim image or a slowd binary).

  slowapp catalog release DIR --ref REF --digest sha256:… --version X.Y.Z [--armv7 SUMMARY]
                              [--base REF] [--changelog CHANGELOG.md]
      After the push: the image's sizes per platform (download, unpacked, and what it adds to a hub
      that has its base already), the version and its changelog, and the armv7 fixture timings.

  slowapp catalog check DIR
      catalog.json against schema/catalog.schema.json, every file's sha256, and the bundle rules.
      What the registry runs on a submission, before its own re-render.
"""
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from slowapp_kit.inks import encode_png, to_indexed

from . import __version__, validate
from .fixture import (FULL, PANEL_W, SLOTS, SLOT_W, STRIP_H, Fail, check_feed, engine, frame, manifest, place,
                      run_example, safe_file)

CATALOG = 1
SCHEMA = Path(__file__).resolve().parent / "schema" / "catalog.schema.json"
# What a `slot` feed may be given on a Lyra: either width of a third, and the whole panel (one slot).
STANDARD_SURFACES = ("452x444.k4", "456x444.k4", "1360x444.k4")
KEYS = {"left": "red", "middle": "yellow", "right": "black", FULL: "red"}   # the layouts' slot keys
SPARE = "white"
WIDTH = {**SLOT_W, FULL: PANEL_W}
X0 = {**{s: x for s, (x, _) in SLOTS.items()}, FULL: 0}
# `slowd compose`'s layout for a feed that is the whole panel (the default is the three thirds).
FULL_LAYOUT = {"strip_h": STRIP_H, "spare_key": SPARE, "prompt_slot": FULL,
               "slots": [{"id": FULL, "x0": 0, "x1": PANEL_W - 1, "key": KEYS[FULL]}]}
CENTRE_SLACK = 8                # slowd centres a body up to this much narrower than its slot
INK_NAMES = {(0, 0, 0): "black", (255, 255, 255): "white", (255, 255, 0): "yellow", (255, 0, 0): "red"}
INK_ORDER = ("black", "white", "yellow", "red", "grey")   # grey: any g16 level between black and white
MAX_UI_GZIP = 512 * 1024        # the registry's rule for a UI bundle (the hub serves up to 2 MB)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ink_set(surface):
    return surface.rsplit(".", 1)[-1]


def save_png(img, path, ink_set="k4"):
    """A screen as its glass sees it: k4 2-bit indexed, the palette exactly the inks; g16 (contract
    5) 8-bit grey on the sixteen levels. Small, stable bytes either way."""
    if ink_set == "g16":
        Path(path).write_bytes(encode_png(img, "g16"))
    else:
        to_indexed(img).save(path, "PNG", bits=2, optimize=False)


def inks(img, ink_set="k4"):
    """The inks a screen uses. Only a g16 screen has greys; any other colour is an error."""
    used = set()
    for _, c in img.convert("RGB").getcolors(1 << 16):
        name = INK_NAMES.get(c)
        if name is None and ink_set == "g16" and c[0] == c[1] == c[2] and c[0] % 17 == 0:
            name = "grey"
        if name is None:
            raise ValueError(f"colour {c} isn't a {ink_set} ink")
        used.add(name)
    return [i for i in INK_ORDER if i in used]


def surface_list(example, feeds, surface):
    """The example's feeds with every `slot` feed at `surface` (fixed feeds keep their size)."""
    return {f: (surface if feeds[f]["size"] == "slot" else s) for f, s in example["feeds"].items()}


# ------------------------------------------------------------------ running

def render(app_dir, m, example, image, surfaces):
    """Run `example` at `surfaces` twice. -> (results per feed: dict or Fail, seconds, metrics, out
    files of the first run). Raises Fail if the job itself fails, or if the two runs differ."""
    ex = {**example, "feeds": surfaces}
    outs = []
    try:
        for _ in range(2):
            out, took, _ = run_example(app_dir, m, ex, image)
            res = {}
            for f, s in surfaces.items():
                try:
                    res[f] = check_feed(out, f, s)
                except Fail as e:
                    res[f] = e
            outs.append((out, took, res))
        (out, took, res), (_, _, res2) = outs
        for f in surfaces:
            a, b = res[f], res2[f]
            if isinstance(a, Fail) or isinstance(b, Fail):
                if isinstance(a, Fail) != isinstance(b, Fail):
                    raise NotDeterministic(f"{f}: one run passed and one failed ({a if isinstance(a, Fail) else b})")
                continue
            ida = {c: v[1] for c, v in a["cards"].items()}
            idb = {c: v[1] for c, v in b["cards"].items()}
            if ida != idb:
                raise NotDeterministic(f"{f} at {surfaces[f]}: the two renders differ\n{ida}\n{idb}")
        metrics = json.loads((out / ".metrics.json").read_text()) if (out / ".metrics.json").exists() else {}
        # Only an example that lists the prompts feed has its prompts.json checked (and shown).
        prompts = json.loads((out / "prompts.json").read_text()) \
            if "prompts" in surfaces and (out / "prompts.json").exists() else None
        return res, took, metrics, prompts
    finally:
        for o in outs:
            shutil.rmtree(o[0].parent, ignore_errors=True)


class NotDeterministic(Exception):
    pass


def reason(err):
    """A failed run in one line: the exit, and the last thing the app said."""
    lines = [l.strip() for l in str(err).splitlines() if l.strip()]
    return (lines[0] + (f": {lines[-1]}" if len(lines) > 1 else ""))[:300] if lines else "failed"


def home_strip(deck, slot):
    cards = deck["cards"]
    if len(cards) >= 2:
        return {"kind": "armed", "key": KEYS[slot], "next": cards[1]["title"], "n": len(cards), "cur": 0, "hold_home": False}
    return {"kind": "single", "title": cards[0]["title"]}


class Composer:
    """Full-panel pictures: `slowd compose` from the slowd-sim image or a binary; without either,
    fixture.frame()'s picture with blank strips (marked strips=false)."""

    def __init__(self, slowd_image=None, slowd=None):
        self.image, self.bin = slowd_image, slowd

    @property
    def strips(self):
        return bool(self.image or self.bin)

    def compose(self, slots, dest, fallback, layout=None):
        """slots: {slot: {"body": Image or None, "strip": spec}} -> writes dest (PNG). `layout`:
        slowd's, if not the default three thirds."""
        if not self.strips:
            save_png(fallback(), dest)
            return
        tmp = Path(tempfile.mkdtemp(prefix="sb-compose-"))
        try:
            spec = {"slots": {}, **({"layout": layout} if layout else {})}
            for s, v in slots.items():
                e = {"strip": v["strip"]}
                if v.get("body") is not None:
                    (tmp / f"{s}.png").write_bytes(encode_png(v["body"]))
                    e["body"] = f"{s}.png"
                spec["slots"][s] = e
            (tmp / "spec.json").write_text(json.dumps(spec))
            os.chmod(tmp, 0o777)
            if self.bin:
                cmd = [self.bin, "compose", str(tmp / "spec.json"), str(tmp / "out.png")]
            else:
                cmd = [engine(), "run", "--rm", "--network", "none", "-v", f"{tmp}:/work", self.image,
                       "compose", "spec.json", "out.png"]
            p = subprocess.run(cmd, capture_output=True, timeout=120)
            if p.returncode:
                raise Fail(f"slowd compose: {p.stderr.decode(errors='replace').strip()[-2000:]}")
            # Re-encoded here so the file (and its sha256) doesn't depend on slowd's PNG encoder.
            save_png(Image.open(tmp / "out.png").convert("RGB"), dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ build

def grants(m):
    p, ui = m["app"], m.get("ui") or {}
    g = {"network": p["network"], "memory": p["memory"], "secrets": p.get("secrets", []),
         "optional_secrets": p.get("optional_secrets", []), "prompts": bool(p.get("prompts")),
         "ui": bool(ui.get("entry")), "backend": bool(ui.get("backend")),
         "imports": p.get("imports", []), "exports": p.get("exports", []),
         "events": (m.get("events") or {}).get("accept", [])}
    if p.get("tmp"):
        g["tmp"] = p["tmp"]
    if (p.get("data") or {}).get("max_mb") is not None:
        g["data_mb"] = p["data"]["max_mb"]
    if (p.get("cache") or {}).get("tmpfs_mb") is not None:
        g["cache_mb"] = p["cache"]["tmpfs_mb"]
    return g


def ui_bundle(m, image):
    entry = (m.get("ui") or {}).get("entry")
    if not entry:
        return None
    eng, tmp = engine(), Path(tempfile.mkdtemp(prefix="sb-ui-"))
    try:
        p = subprocess.run([eng, "create", image], capture_output=True, text=True)
        if p.returncode:
            raise Fail(f"[ui] can't create a container from {image}: {p.stderr.strip()}")
        cid = p.stdout.strip()
        try:
            p = subprocess.run([eng, "cp", f"{cid}:{entry}", str(tmp / "ui.html")], capture_output=True, text=True)
            if p.returncode:
                raise Fail(f"[ui] entry {entry} isn't in the image: {p.stderr.strip()}")
        finally:
            subprocess.run([eng, "rm", cid], capture_output=True)
        data = (tmp / "ui.html").read_bytes()
        return {"entry": entry, "bytes": len(data), "gzip_bytes": len(gzip.compress(data, 9, mtime=0)),
                "sha256": hashlib.sha256(data).hexdigest()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def author(m, app_dir):
    repo = m["app"].get("repo", "")
    mt = re.match(r"https://github\.com/([^/]+)/", repo)
    return os.environ.get("SLOWAPP_AUTHOR") or (mt and mt.group(1)) or os.environ.get("GITHUB_REPOSITORY_OWNER") or ""


def cmd_build(a):
    app_dir, out_dir = Path(a.dir), Path(a.out)
    try:
        m = manifest(app_dir)
    except Fail as e:
        print(f"FAIL  {e}")
        return 1
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "screens").mkdir(parents=True)
    p, feeds = m["app"], {f["name"]: f for f in m.get("feed", [])}
    comp = Composer(a.slowd_image, a.slowd)
    if not comp.strips:
        print("note  no --slowd-image or --slowd: full-panel pictures get blank strips")
    plat = os.environ.get("SLOWAPP_PLATFORM") or "linux/" + {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(os.uname().machine, os.uname().machine)
    screens, examples, support, failed = [], [], {}, 0
    seen, names = set(), set()

    def add_screens(ex, res):
        for f, r in res.items():
            if isinstance(r, Fail):
                continue
            surface = ex_surfaces[f]
            if (ex["name"], f, surface) in seen:
                continue
            seen.add((ex["name"], f, surface))
            for c in r["deck"]["cards"]:
                img = r["cards"][c["id"]][0]
                # Card ids may carry characters safe_file maps to '_' (prompt ids carry ':'), so a
                # name already taken gets ~N, which safe_file never leaves in one.
                rel, n = f"screens/{ex['name']}/{surface}/{f}/{safe_file(c['id'])}.png", 1
                while rel in names:
                    n += 1
                    rel = f"screens/{ex['name']}/{surface}/{f}/{safe_file(c['id'])}~{n}.png"
                names.add(rel)
                (out_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                save_png(img, out_dir / rel, ink_set(surface))
                if r.get("prompts"):
                    kind = "ask" if c["id"].endswith(".ask") else "answer"
                else:
                    kind = c.get("kind", "detail")
                s = {"example": ex["name"], "feed": f, "surface": surface, "card": c["id"], "kind": kind,
                     "title": c["title"], "file": rel, "sha256": sha256(out_dir / rel), "inks": inks(img, ink_set(surface))}
                if kind == "answer":
                    s["binding"] = ".".join(c["id"].rsplit(".", 2)[-2:])
                screens.append(s)

    for ex in m.get("example", []):
        e = {"name": ex["name"], "now": ex["now"], "job": ex.get("job", "render"), "feeds": dict(ex["feeds"])}
        for k in ("caption", "tz", "settings"):
            if k in ex:
                e[k] = ex[k]
        try:
            ex_surfaces = dict(ex["feeds"])
            res, took, metrics, prompts = render(app_dir, m, ex, a.image, ex_surfaces)
            bad = {f: r for f, r in res.items() if isinstance(r, Fail)}
            if bad:
                raise Fail("; ".join(str(r) for r in bad.values()))
            for f, s in ex_surfaces.items():
                support.setdefault(f, {}).setdefault(s, []).append((ex["name"], None))
            add_screens(ex, res)
            e.update(seconds=round(took, 1), platform=plat)
            if metrics.get("memory_peak_kb") is not None:
                e["memory_peak_kb"] = metrics["memory_peak_kb"]
            e["frames"] = frames(out_dir, ex, res, prompts, comp)
            if prompts:
                e["prompts"] = [{"id": q["id"], "question": q["question"], "ask": q.get("ask") is not None,
                                 "slot_hint": q.get("slot_hint") or "", "bindings": {
                                     b: v.get("strip") or b for b, v in (q.get("bindings") or {}).items()}}
                                for q in prompts.get("prompts", [])]
            print(f"ok    {ex['name']:16} {took:6.1f} s  " + "  ".join(f"{f} {s}" for f, s in ex_surfaces.items()))
        except (Fail, NotDeterministic) as err:
            failed += 1
            print(f"FAIL  {ex['name']:16} {err}")
            e.update(error=str(err)[:3000])
            examples.append(e)
            continue
        # The same example at every other standard surface its slot feeds could be given.
        for s in STANDARD_SURFACES:
            ex_surfaces = surface_list(ex, feeds, s)
            if ex_surfaces == dict(ex["feeds"]):
                continue
            todo = {f for f, v in ex_surfaces.items() if feeds[f]["size"] == "slot"}
            try:
                res, took, _, _ = render(app_dir, m, ex, a.image, ex_surfaces)
                for f in todo:
                    r = res[f]
                    support.setdefault(f, {}).setdefault(s, []).append((ex["name"], str(r) if isinstance(r, Fail) else None))
                add_screens(ex, {f: res[f] for f in todo})
                print(f"      {ex['name']:16} at {s}: " + ", ".join(f"{f} {'no' if isinstance(res[f], Fail) else 'ok'}" for f in sorted(todo)))
            except NotDeterministic as err:
                failed += 1
                print(f"FAIL  {ex['name']:16} at {s}: {err}")
                e.setdefault("errors", []).append(f"{s}: {err}"[:3000])
            except Fail as err:
                why = reason(err)
                for f in todo:
                    support.setdefault(f, {}).setdefault(s, []).append((ex["name"], why))
                print(f"      {ex['name']:16} at {s}: unsupported ({why})")
        examples.append(e)

    rows = {}
    for name in feeds:
        surfaces = rows[name] = {}
        order = lambda kv: (STANDARD_SURFACES.index(kv[0]) if kv[0] in STANDARD_SURFACES else 99, kv[0])  # noqa: E731
        for s, runs in sorted(support.get(name, {}).items(), key=order):
            # Per example, one good render at a size is enough: a run that gives every slot feed
            # the same size can fail because of another feed (or the job checks its layout).
            good = {ex for ex, err in runs if err is None}
            errs = sorted({f"{ex}: {err}" for ex, err in runs if err and ex not in good})
            surfaces[s] = {"ok": not errs, **({"error": "; ".join(errs)[:1000]} if errs else {})}
    # A screen from a good render at a size another example fails at: the size is unsupported, so
    # the screen goes (check() takes screens only at supported sizes).
    for x in [x for x in screens if not rows[x["feed"]].get(x["surface"], {}).get("ok")]:
        screens.remove(x)
        (out_dir / x["file"]).unlink(missing_ok=True)
    feed_rows = []
    for name, f in feeds.items():
        surfaces = rows[name]
        mine = [x for x in screens if x["feed"] == name]
        # Screens per example at its own size: the most any example shows, by kind.
        counts = {}
        for e in examples:
            per = {}
            for x in mine:
                if x["example"] == e["name"] and x["surface"] == e["feeds"].get(name):
                    per[x["kind"]] = per.get(x["kind"], 0) + 1
            for k, n in per.items():
                counts[k] = max(counts.get(k, 0), n)
        feed_rows.append({"name": name, "size": f["size"], "surfaces": surfaces,
                          "supported": [s for s, v in surfaces.items() if v["ok"]],
                          "inks": [i for i in INK_ORDER if any(i in x["inks"] for x in mine)], "screens": counts})

    cat = {
        "catalog": CATALOG,
        "app": {k: p[k] for k in ("id", "title", "contract", "image", "blurb", "about", "ink", "license", "repo") if k in p},
        "manifest": json.loads(json.dumps(m, default=str)),
        "manifest_sha256": sha256(app_dir / "slowapp.toml"),
        "grants": grants(m),
        "feeds": feed_rows,
        "examples": examples,
        "screens": screens,
        "standard_surfaces": list(STANDARD_SURFACES),
        "made": {"at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "sdk": __version__,
                 "slowd": a.slowd_image or (a.slowd and "binary") or "none", "platform": plat},
    }
    who = author(m, app_dir)
    if who:
        cat["app"]["author"] = who
    try:
        ui = ui_bundle(m, a.image)
    except Fail as err:
        failed += 1
        print(f"FAIL  ui: {err}")
        ui = None
    if ui:
        cat["ui"] = ui
    (out_dir / "catalog.json").write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n")
    (out_dir / "report.md").write_text(report(cat))
    errs = check(out_dir)
    for err in errs:
        print(f"FAIL  check: {err}")
    print(f"{len(screens)} screens, {sum(len(e.get('frames', [])) for e in examples)} full-panel pictures; "
          f"{len(examples) - failed}/{len(examples)} examples ok; bundle in {out_dir}")
    return 1 if failed or errs else 0


def frames(out_dir, ex, res, prompts, comp):
    """The full-panel pictures of one example: its home cards with their strips, and, if it asks
    a question, the first prompt on its slot. None for an example with no board feed (contract 5:
    only feeds for other glass, such as a sleep screen's strip)."""
    placed = place(res)
    if not placed:
        return []
    full = FULL in placed.values()
    layout = FULL_LAYOUT if full else None
    slots = {}
    for f, s in placed.items():
        r = res[f]
        home = r["deck"]["cards"][0]["id"]
        slots[s] = {"body": r["cards"][home][0], "strip": home_strip(r["deck"], s)}
    out = []
    name = ex["name"]
    rel = f"screens/{name}/panel-home.png"
    (out_dir / rel).parent.mkdir(parents=True, exist_ok=True)
    comp.compose(slots, out_dir / rel, lambda: frame(res), layout)
    out.append({"kind": "home", "file": rel, "sha256": sha256(out_dir / rel), "strips": comp.strips})
    if prompts and prompts.get("prompts"):
        q = prompts["prompts"][0]
        ask = res["prompts"]["cards"][f"{q['id']}.ask"][0] if q.get("ask") is not None else None
        # The hinted slot (else the layout's prompt slot), or the first one the card fits.
        ids = [FULL] if full else list(SLOTS)
        hint = q.get("slot_hint") if q.get("slot_hint") in ids else ids[-1]
        fit = [s for s in [hint] + ids if ask is None or 0 <= WIDTH[s] - ask.width <= CENTRE_SLACK]
        if not fit:
            print(f"note  {name}: no slot fits prompt {q['id']}'s {ask.width} px card; no prompt picture")
            return out
        slot = fit[0]
        body = ask if ask is not None else (slots.get(slot) or {}).get("body")
        ps = dict(slots)
        ps[slot] = {"body": body, "strip": {"kind": "prompt", "key": KEYS[slot], "spare": SPARE,
                                             "question": q["question"], "answers_only": q.get("ask") is not None}}
        rel = f"screens/{name}/panel-prompt.png"

        def flat():
            img = frame(res)
            if body is not None:
                img.paste((255, 255, 255), (X0[slot], 0, X0[slot] + WIDTH[slot], body.height))
                img.paste(body, (X0[slot] + (WIDTH[slot] - body.width) // 2, 0))
            return img
        comp.compose(ps, out_dir / rel, flat, layout)
        out.append({"kind": "prompt", "file": rel, "sha256": sha256(out_dir / rel), "strips": comp.strips,
                    "prompt": q["id"]})
    return out


def report(cat):
    lines = [f"### Catalog: {cat['app']['title']} ({len(cat['screens'])} screens)", "",
             "| feed | sizes | unsupported | inks | screens per example |", "|---|---|---|---|---|"]
    for f in cat["feeds"]:
        no = [f"{s} ({v.get('error', '')[:80]})" for s, v in f["surfaces"].items() if not v["ok"]]
        lines.append(f"| {f['name']} | {', '.join(f['supported']) or 'none'} | {'; '.join(no) or '-'} | "
                     f"{' '.join(i[0].upper() for i in f['inks'])} | "
                     f"{', '.join(f'{n} {k}' for k, n in f['screens'].items())} |")
    lines.append("")
    for e in cat["examples"]:
        lines.append(f"- **{e['name']}**: " + (f"FAILED: {e['error'][:200]}" if "error" in e else
                     f"{e['seconds']} s, peak {e.get('memory_peak_kb', '?')} kB, " +
                     ", ".join(fr["file"] for fr in e["frames"])))
    if "ui" in cat:
        lines.append(f"- UI bundle {cat['ui']['entry']}: {cat['ui']['bytes']} bytes, {cat['ui']['gzip_bytes']} gzipped")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ release

def base_of(dockerfile):
    """The image the final stage builds on: the last FROM, past its --flags, with the ARG defaults
    declared before the first FROM filled in and an earlier stage's name followed to its image.
    app.yml's BASE_OF awk does the same."""
    args, stages, base = {}, {}, None
    for line in Path(dockerfile).read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0].upper() == "ARG" and base is None and len(parts) > 1:
            k, eq, v = parts[1].partition("=")
            if eq:
                args[k] = v.strip("\"'")
        elif parts[0].upper() == "FROM":
            rest = [w for w in parts[1:] if not w.startswith("--")]
            if not rest:
                continue
            img = re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda mt: args.get(mt[1] or mt[2], mt[0]), rest[0])
            base = stages.get(img.lower(), img)
            if len(rest) > 2 and rest[1].upper() == "AS":
                stages[rest[2].lower()] = base
    return base


def changelog_for(path, version):
    """The `## X.Y.Z` (or `## vX.Y.Z`, `## [X.Y.Z]`) section of a changelog, without its heading."""
    try:
        text = Path(path).read_text()
    except OSError:
        return None
    out, on = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            if on:
                break
            on = bool(re.match(rf"##\s+\[?v?{re.escape(version)}\]?(\s|$)", line))
            continue
        if on:
            out.append(line)
    return "\n".join(out).strip() or None


def cmd_release(a):
    out_dir = Path(a.dir)
    cat = json.loads((out_dir / "catalog.json").read_text())
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", a.digest):
        print(f"FAIL  --digest {a.digest!r} isn't sha256:<64 hex>")
        return 1
    base = a.base or base_of(Path(a.app_dir) / "Dockerfile")
    from . import oci
    try:
        plats = oci.sizes(f"{a.ref}@{a.digest}", base=base)
    except oci.RegistryError as e:
        print(f"FAIL  image sizes: {e}")
        return 1
    cat["image"] = {"ref": a.ref, "digest": a.digest, "platforms": plats}
    if base:
        cat["image"]["base"] = base
    rel = {"version": a.version, "tag": f"v{a.version}"}
    notes = changelog_for(a.changelog, a.version) if a.changelog else None
    if notes:
        rel["changelog"] = notes[:8000]
    cat["release"] = rel
    cat["app"]["version"] = a.version
    if a.armv7:
        runs = json.loads(Path(a.armv7).read_text())
        by = {r["example"]: r for r in runs if r.get("ok")}
        cat["measured"] = {"linux/arm/v7": {n: {k: v for k, v in {"seconds": r.get("seconds"),
                           "memory_peak_kb": (r.get("metrics") or {}).get("memory_peak_kb")}.items() if v is not None}
                           for n, r in by.items()}, "note": "fixture runs in CI, armv7 under QEMU"}
    (out_dir / "catalog.json").write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n")
    for plat, r in plats.items():
        un = f", {r['unpacked'] / 1e6:.1f} MB unpacked (+{r['adds_unpacked'] / 1e6:.1f} MB)" if "unpacked" in r else ""
        print(f"      {plat:14} {r['download'] / 1e6:.1f} MB download (+{r['adds_download'] / 1e6:.1f} MB on a hub with the base){un}")
    errs = check(out_dir)
    for err in errs:
        print(f"FAIL  check: {err}")
    return 1 if errs else 0


# ------------------------------------------------------------------ check

def check(out_dir):
    """Errors in a bundle: the schema, the files and their hashes, and the cross-field rules."""
    out_dir = Path(out_dir)
    try:
        cat = json.loads((out_dir / "catalog.json").read_text())
    except (OSError, ValueError) as e:
        return [f"catalog.json: {e}"]
    schema = json.loads(SCHEMA.read_text())
    errs = validate.schema_errors(cat, schema, schema)
    if errs:
        return errs
    root = out_dir.resolve()

    def file_ok(rel, digest, what):
        path = (out_dir / rel).resolve()
        if root not in path.parents:
            errs.append(f"{what}: {rel} is outside the bundle")
        elif not path.is_file():
            errs.append(f"{what}: {rel} is missing")
        elif sha256(path) != digest:
            errs.append(f"{what}: {rel} doesn't match its sha256")

    m = cat["manifest"]
    if m.get("app", {}).get("id") != cat["app"]["id"]:
        errs.append("app.id isn't the manifest's")
    _, merrs, _ = validate_manifest(m)
    errs += [f"manifest: {e}" for e in merrs]
    feeds = {f["name"]: f for f in cat["feeds"]}
    declared = {f["name"]: f for f in m.get("feed", [])}
    if set(feeds) != set(declared):
        errs.append(f"feeds {sorted(feeds)} aren't the manifest's {sorted(declared)}")
    examples = {e["name"]: e for e in cat["examples"]}
    for s in cat["screens"]:
        what = f"screen {s['example']}/{s['feed']}/{s['card']}@{s['surface']}"
        file_ok(s["file"], s["sha256"], what)
        if s["example"] not in examples or s["feed"] not in feeds:
            errs.append(f"{what}: unknown example or feed")
        elif s["surface"] not in feeds[s["feed"]]["supported"]:
            errs.append(f"{what}: {s['surface']} isn't a supported surface of {s['feed']}")
    for e in cat["examples"]:
        for fr in e.get("frames", []):
            file_ok(fr["file"], fr["sha256"], f"{e['name']} {fr['kind']} picture")
        board = any(ink_set(s) == "k4" and f != "prompts" for f, s in e["feeds"].items())
        if "error" not in e and board and not e.get("frames"):
            errs.append(f"example {e['name']}: no full-panel picture")
    # Exhaustive: every example that has a feed shows it at every size the feed supports.
    have = {(s["example"], s["feed"], s["surface"]) for s in cat["screens"]}
    for f in cat["feeds"]:
        if f["supported"] != [s for s, v in f["surfaces"].items() if v["ok"]]:
            errs.append(f"feed {f['name']}: supported doesn't list exactly its ok surfaces")
        for e in cat["examples"]:
            if f["name"] in e["feeds"] and "error" not in e:
                for s in f["supported"]:
                    if (e["name"], f["name"], s) not in have:
                        errs.append(f"feed {f['name']}: no screens of example {e['name']} at {s}")
    if "ui" in cat and cat["ui"]["gzip_bytes"] > MAX_UI_GZIP:
        errs.append(f"ui: {cat['ui']['gzip_bytes']} bytes gzipped, the catalog takes at most {MAX_UI_GZIP}")
    return errs


def validate_manifest(m):
    schema = json.loads(validate.SCHEMA.read_text())
    errs = validate.schema_errors(m, schema, schema)
    if errs:
        return m, errs, []
    e2, warns = validate.rule_errors(m)
    return m, e2, warns


def cmd_check(a):
    errs = check(a.dir)
    for e in errs:
        print(f"error   {e}")
    print("ok" if not errs else f"FAIL    {len(errs)} problems")
    return 1 if errs else 0
