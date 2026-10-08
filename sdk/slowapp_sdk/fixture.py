"""Run an app in fixture mode the way the hub will, check what it writes to /out, and make previews.

  slowapp fixture [DIR] --image IMAGE [--out out/previews] [--repeat]

Runs every [[example]] of DIR/slowapp.toml (default .) from IMAGE, then checks every requested
feed: deck.json, card ids and kinds, each card an exact-size indexed PNG in the inks (the same
check the kit and the hub make). It writes, per example, each card as
<app>-<example>-<feed>-<card>.png, the home cards spliced into a full 1360x480 frame
(<app>-<example>-frame.png), and for the run summary.json (blob ids, timings, exit codes,
metrics) and report.md. --repeat runs each example twice and fails unless the blob ids match:
the same fixture must give the same pixels.

The engine is podman if installed, else docker (SLOWAPP_ENGINE overrides). SLOWAPP_PLATFORM
(e.g. linux/arm/v7) is passed as --platform to run the board's images under QEMU, and
SLOWAPP_TIMEOUT_SCALE stretches the manifest's timeout for it. Needs Pillow.
"""
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image

from slowapp_kit.inks import InkError, blob_id, check_png

from . import validate

CONTRACT = 3
SLOTS = {"left": (0, "red"), "middle": (452, "yellow"), "right": (908, "black")}   # the default layout
SLOT_W = {"left": 452, "middle": 456, "right": 452}
PANEL_W, PANEL_H, STRIP_H = 1360, 480, 36
EXIT_NAMES = {0: "ok", 3: "unchanged", 4: "transient", 5: "needs config", 64: "contract error", 137: "killed"}


def safe_file(name):
    """A preview file name CI artifacts accept: prompt instance ids carry times (`:`)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


class Fail(Exception):
    pass


# ------------------------------------------------------------------ manifests

def manifest(app_dir):
    m, errs, _ = validate.validate(app_dir)
    if errs:
        raise Fail(f"invalid manifest: {errs[0]}")
    return m


def feeds_env(example):
    out = []
    for feed, surface in example["feeds"].items():
        size, inks = surface.split(".")
        w, h = (int(v) for v in size.split("x"))
        slot = feed if feed in SLOTS else None
        out.append({"feed": feed, "slot": slot, "w": w, "h": h, "inks": inks, "bpp": 2,
                    "key": SLOTS[slot][1] if slot else None})
    return out


# ------------------------------------------------------------------ running

def engine():
    e = os.environ.get("SLOWAPP_ENGINE") or next((x for x in ("podman", "docker") if shutil.which(x)), None)
    if not e:
        raise Fail("no container engine: install podman or docker, or set SLOWAPP_ENGINE")
    return e


def run_args(m, example, image, data, out, inp, run_id, name, rundir):
    """The fixture-mode command line: the hub's run flags with fixture mode's overrides. Everything
    the app can reach is here.

    A CI subset on purpose: no --cidfile / --conmon-pidfile (the hub's supervisor bookkeeping), no
    --log-driver none (this runner reports the app's stderr), no secrets and no /imports (fixture
    mode), and sb.hub=ci (there's no hub boot id). /run/sb is mounted as for a real job, though only
    `serve` uses it."""
    p = m["app"]
    job = example.get("job", "render")
    args = ["run", "--rm", "--name", name,
            "--label", f"sb.app={p['id']}", "--label", "sb.kind=job", "--label", "sb.hub=ci",
            "--label", f"sb.run={run_id}",
            "--read-only", "--tmpfs", f"/tmp:rw,size={p.get('tmp', '16m')}",
            "--network", "none",
            "--memory", p["memory"], "--memory-swap", p["memory"], "--pids-limit", "64", "--oom-score-adj", "500",
            "--cap-drop", "all", "--security-opt", "no-new-privileges",
            "-v", f"{data}:/data:ro", "-v", f"{out}:/out", "-v", f"{inp}:/in:ro", "-v", f"{rundir}:/run/sb"]
    if p.get("cache", {}).get("tmpfs_mb"):
        args += ["--tmpfs", f"/cache:rw,size={p['cache']['tmpfs_mb']}m"]
    if os.environ.get("SLOWAPP_PLATFORM"):
        args += ["--platform", os.environ["SLOWAPP_PLATFORM"]]
    env = {"SLOWAPP_CONTRACT": str(CONTRACT), "SLOWAPP_APP": p["id"], "SLOWAPP_JOB": job, "SLOWAPP_RUN_ID": run_id,
           "SLOWAPP_REASON": "fixture", "SLOWAPP_MODE": "fixture", "SLOWAPP_NOW": example["now"],
           "SLOWAPP_FOR": example["now"], "TZ": example.get("tz", "America/Vancouver"),
           "SLOWAPP_FEEDS": json.dumps(feeds_env(example)), "SLOWAPP_STATE": "/data"}
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    return args + [image, "job", job]


def run_example(app_dir, m, example, image):
    """Run one example. Returns (out dir, seconds, stderr tail)."""
    app = m["app"]["id"]
    eng, run_id = engine(), f"r_fx_{uuid.uuid4().hex[:10]}"
    tmp = Path(tempfile.mkdtemp(prefix=f"sb-{app}-"))
    data, out, inp, rundir = tmp / "data", tmp / "out", tmp / "in", tmp / "run-sb"
    shutil.copytree(Path(app_dir) / example["fixture"], data)
    out.mkdir()
    inp.mkdir()
    rundir.mkdir()
    (inp / "settings.json").write_text(json.dumps(example.get("settings", {})))
    (inp / "layout.json").write_text(json.dumps({"strip_h": STRIP_H}))
    for d in (data, out, inp, rundir):
        os.chmod(d, 0o777)                       # rootless engines map container root elsewhere
    name = f"sb-{app}-{run_id[-6:]}"
    cmd = [eng] + run_args(m, example, image, data, out, inp, run_id, name, rundir)
    timeout = m["app"]["timeout_s"] * (int(os.environ.get("SLOWAPP_TIMEOUT_SCALE", "1")))
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run([eng, "rm", "-f", name], capture_output=True)
        raise Fail(f"timed out after {timeout} s")
    took = time.monotonic() - t0
    err = p.stderr.decode(errors="replace")
    if p.returncode:
        raise Fail(f"exit {p.returncode} ({EXIT_NAMES.get(p.returncode, 'failed')})\n{err[-3000:]}")
    return out, took, err[-2000:]


# ------------------------------------------------------------------ checking /out

def check_out(out, example):
    """-> {feed: {"deck": deck, "cards": {id: (rgb image, blob id)}}}. Raises Fail on any contract break."""
    res = {}
    for feed, surface in example["feeds"].items():
        size = tuple(int(v) for v in surface.split(".")[0].split("x"))
        if feed == "prompts":
            res[feed] = check_prompts(out, surface, size)
            continue
        root = out / "feeds" / feed
        try:
            deck = json.loads((root / "deck.json").read_text())
        except (OSError, ValueError) as e:
            raise Fail(f"{feed}: deck.json: {e}")
        cards = deck.get("cards")
        if not isinstance(cards, list) or not 1 <= len(cards) <= 32:
            raise Fail(f"{feed}: deck.json needs 1-32 cards")
        try:
            vf, vu = (datetime.fromisoformat(deck[k]) for k in ("valid_from", "valid_until"))
        except (KeyError, TypeError, ValueError) as e:
            raise Fail(f"{feed}: valid_from / valid_until: {e}")
        if vf.tzinfo is None or vu.tzinfo is None or vu <= vf:
            raise Fail(f"{feed}: valid_from / valid_until need offsets and valid_until > valid_from")
        got = {}
        for i, c in enumerate(cards):
            if c.get("kind") != ("home" if i == 0 else "detail"):
                raise Fail(f"{feed}/{c.get('id')}: kind {c.get('kind')!r}; the first card is home, the rest detail")
            if not c.get("title"):
                raise Fail(f"{feed}/{c.get('id')}: no title")
            try:
                data = (root / "cards" / f"{c['id']}.png").read_bytes()
                rgb = check_png(data, size)
            except (OSError, InkError, KeyError) as e:
                raise Fail(f"{feed}/{c.get('id')}: {e}")
            got[c["id"]] = (rgb, blob_id(rgb))
        res[feed] = {"deck": deck, "cards": got}
    for extra in ("summary.json", ".metrics.json"):
        if (out / extra).exists():
            json.loads((out / extra).read_text())
    return res


BINDINGS = ("own.tap", "spare.tap", "own.hold", "spare.hold")


def check_prompts(out, surface, size):
    """The prompts grant's output: /out/prompts.json and each binding's body. Returned in the
    deck shape (one pseudo-card per binding, `<instance>.<binding>`) so previews and the report
    treat it like a feed; frame() leaves it out (prompts are overlays, not a slot's home)."""
    try:
        doc = json.loads((out / "prompts.json").read_text())
    except (OSError, ValueError) as e:
        raise Fail(f"prompts: prompts.json: {e}")
    if doc.get("surface") != surface:
        raise Fail(f"prompts: surface {doc.get('surface')!r}, the example asks {surface}")
    prompts = doc.get("prompts")
    if not isinstance(prompts, list) or len(prompts) > 8:
        raise Fail("prompts: prompts.json needs a list of at most 8 prompts")
    cards, got = [], {}
    for p in prompts:
        pid = p.get("id", "?")
        try:
            vf, vu = (datetime.fromisoformat(p[k]) for k in ("from", "until"))
        except (KeyError, TypeError, ValueError) as e:
            raise Fail(f"prompts/{pid}: from / until: {e}")
        if vf.tzinfo is None or vu.tzinfo is None or vu <= vf:
            raise Fail(f"prompts/{pid}: from / until need offsets and until > from")
        if not p.get("question"):
            raise Fail(f"prompts/{pid}: no question")
        if p.get("ask") is not None:
            want = f"prompts/{pid}/ask.png"
            if p["ask"] != want:
                raise Fail(f"prompts/{pid}: ask must be {want}")
            try:
                rgb = check_png((out / want).read_bytes(), size)
            except (OSError, InkError) as e:
                raise Fail(f"prompts/{pid}.ask: {e}")
            got[f"{pid}.ask"] = (rgb, blob_id(rgb))
            cards.append({"id": f"{pid}.ask", "title": p["question"]})
        bindings = p.get("bindings") or {}
        if not bindings or not set(bindings) <= set(BINDINGS):
            raise Fail(f"prompts/{pid}: bindings {sorted(bindings)} (1-4 of {', '.join(BINDINGS)})")
        for name, b in bindings.items():
            cid = f"{pid}.{name}"
            try:
                rgb = check_png((out / b["show"]).read_bytes(), size)
            except (OSError, InkError, KeyError) as e:
                raise Fail(f"prompts/{cid}: {e}")
            got[cid] = (rgb, blob_id(rgb))
            cards.append({"id": cid, "title": f"{p['question']} → {b.get('strip') or name}"})
    return {"deck": {"cards": cards}, "cards": got, "prompts": True}


def frame(res):
    """Home cards spliced into a white full frame, strips left blank (slowbd draws them). A feed
    named after a slot goes there; any other takes the next free slot whose width matches."""
    img = Image.new("RGB", (PANEL_W, PANEL_H), (255, 255, 255))
    res = {f: r for f, r in res.items() if not r.get("prompts")}
    free = list(SLOTS)
    placed = {f: f for f in res if f in SLOTS}
    for f in placed:
        free.remove(f)
    for feed, r in res.items():
        if feed not in placed:
            home = r["cards"][r["deck"]["cards"][0]["id"]][0]
            fits = [s for s in free if SLOT_W[s] == home.width]
            if fits:
                placed[feed] = fits[0]
                free.remove(fits[0])
    for feed, slot in placed.items():
        r = res[feed]
        home = r["deck"]["cards"][0]["id"]
        img.paste(r["cards"][home][0], (SLOTS[slot][0], 0))
    for x in (451, 907):
        for y in range(PANEL_H - STRIP_H, PANEL_H, 2):
            img.putpixel((x, y), (0, 0, 0))
    return img


# ------------------------------------------------------------------ commands

def cmd_test(a):
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results, failed = [], 0
    try:
        m = manifest(a.dir)
    except Fail as e:
        print(f"FAIL  {e}")
        return 1
    app = m["app"]["id"]
    for ex in m.get("example", []):
        r = dict(app=app, example=ex["name"], caption=ex.get("caption", ""), now=ex["now"])
        try:
            out, took, err = run_example(a.dir, m, ex, a.image)
            res = check_out(out, ex)
            ids = {f: {cid: v[1] for cid, v in x["cards"].items()} for f, x in res.items()}
            if a.repeat:
                out2, took2, _ = run_example(a.dir, m, ex, a.image)
                ids2 = {f: {cid: v[1] for cid, v in x["cards"].items()} for f, x in check_out(out2, ex).items()}
                if ids2 != ids:
                    raise Fail(f"not deterministic: blob ids differ between two runs\n{ids}\n{ids2}")
                shutil.rmtree(out2.parent, ignore_errors=True)
            files = []
            for f, x in res.items():
                for cid, (img, _) in x["cards"].items():
                    fn = safe_file(f"{app}-{ex['name']}-{f}-{cid}.png")
                    img.save(out_dir / fn)
                    files.append(fn)
            fn = f"{app}-{ex['name']}-frame.png"
            frame(res).save(out_dir / fn)
            metrics = json.loads((out / ".metrics.json").read_text()) if (out / ".metrics.json").exists() else {}
            summary = json.loads((out / "summary.json").read_text()) if (out / "summary.json").exists() else None
            r.update(ok=True, seconds=round(took, 1), frame=fn, files=files, blobs=ids, metrics=metrics,
                     summary=summary, decks={f: x["deck"] for f, x in res.items()},
                     deterministic=bool(a.repeat) or None)
            print(f"ok    {ex['name']:16} {took:6.1f} s  " +
                  "  ".join(f"{f}: {len(v)} cards" for f, v in ids.items()))
            for f, v in ids.items():
                for cid, bid in v.items():
                    print(f"        {f}/{cid}: {bid}")
            shutil.rmtree(out.parent, ignore_errors=True)
        except Fail as e:
            failed += 1
            r.update(ok=False, error=str(e))
            print(f"FAIL  {ex['name']:16} {e}")
        results.append(r)
    (out_dir / "summary.json").write_text(json.dumps(results, indent=1))
    (out_dir / "report.md").write_text(report(results))
    print(f"{len(results) - failed}/{len(results)} examples passed; previews in {out_dir}")
    return 1 if failed else 0


def report(results):
    plat = os.environ.get("SLOWAPP_PLATFORM") or "native"
    ok = sum(r["ok"] for r in results)
    lines = [f"### Previews: {ok}/{len(results)} examples passed ({plat}, fixture mode)", ""]
    for r in results:
        lines.append(f"#### {r['app']} / {r['example']}" + (f": {r['caption']}" if r.get("caption") else ""))
        lines.append("")
        if not r["ok"]:
            lines += ["```", r["error"][:3000], "```", ""]
            continue
        mt = r.get("metrics", {})
        lines.append(f"{r['seconds']} s · peak {mt.get('memory_peak_kb', '?')} kB (cgroup) · "
                     f"maxrss {mt.get('ru_maxrss_kb', '?')} kB · frame `{r['frame']}`"
                     + (" · deterministic over two runs" if r.get("deterministic") else ""))
        lines.append("")
        lines.append("| feed | card | title | blob id |")
        lines.append("|---|---|---|---|")
        for f, deck in r["decks"].items():
            for c in deck["cards"]:
                lines.append(f"| {f} | {c['id']} | {c['title']} | `{r['blobs'][f][c['id']][:16]}…` |")
        lines.append("")
    return "\n".join(lines) + "\n"
