"""Validate an app manifest (slowapp.toml) against contracts 3 to 6.

  slowapp validate            ./slowapp.toml
  slowapp validate DIR ...    each DIR/slowapp.toml (or a path to the file)

Two layers: the structural JSON Schema in schema/slowapp.schema.json (checked by a small built-in
interpreter, so no dependencies beyond Python 3.11), then the cross-field rules below, which a
schema can't say. The rules are documented in MANIFEST.md. Exit 1 on any error.
"""
import json
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "schema" / "slowapp.schema.json"
SLOT_SURFACES = {"452x444.k4", "456x444.k4"}   # the default thirds with a 36 px strip (epd/layout.py)


# ------------------------------------------------------------------ JSON Schema (the subset we use)

def _type_ok(v, t):
    return {"object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str),
            "boolean": isinstance(v, bool), "null": v is None,
            "integer": isinstance(v, int) and not isinstance(v, bool),
            "number": isinstance(v, (int, float)) and not isinstance(v, bool)}[t]


def schema_errors(v, s, root, path="$"):
    """Errors for value v against schema s: type, enum, const, pattern, minLength, maxLength,
    minimum, maximum, required, properties, additionalProperties, propertyNames, minProperties,
    items, minItems, uniqueItems, $ref (local)."""
    if "$ref" in s:
        node = root
        for part in s["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return schema_errors(v, node, root, path)
    errs = []
    if "type" in s and not _type_ok(v, s["type"]):
        return [f"{path}: expected {s['type']}, got {type(v).__name__}"]
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: must be {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} is not one of {s['enum']}")
    if isinstance(v, str):
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{path}: {v!r} doesn't match {s['pattern']}")
        if len(v) < s.get("minLength", 0) or len(v) > s.get("maxLength", 1 << 30):
            errs.append(f"{path}: length {len(v)} is out of range")
    if _type_ok(v, "number"):
        if "minimum" in s and v < s["minimum"]:
            errs.append(f"{path}: {v} < {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            errs.append(f"{path}: {v} > {s['maximum']}")
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{path}: missing {k!r}")
        if len(v) < s.get("minProperties", 0):
            errs.append(f"{path}: needs at least {s['minProperties']} entries")
        props = s.get("properties", {})
        for k, sub in v.items():
            if "propertyNames" in s:
                errs += schema_errors(k, s["propertyNames"], root, f"{path}.{k} (name)")
            if k in props:
                errs += schema_errors(sub, props[k], root, f"{path}.{k}")
            elif s.get("additionalProperties") is False:
                errs.append(f"{path}: unknown key {k!r}")
            elif isinstance(s.get("additionalProperties"), dict):
                errs += schema_errors(sub, s["additionalProperties"], root, f"{path}.{k}")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            errs.append(f"{path}: needs at least {s['minItems']} items")
        if s.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
            errs.append(f"{path}: items must be unique")
        if "items" in s:
            for i, x in enumerate(v):
                errs += schema_errors(x, s["items"], root, f"{path}[{i}]")
    return errs


# ------------------------------------------------------------------ cross-field rules

def mb(size):
    n, unit = int(size[:-1]), size[-1]
    return n / 1024 if unit == "k" else n * 1024 if unit == "g" else n


def minutes(every):
    return int(every[:-1]) * (60 if every.endswith("h") else 1)


def job_kind(m, j):
    """A job's kind: contract 6 jobs are `render` unless they say `sync`; before 6 a job has no
    kind (None): every job may have the app's network and secrets."""
    return j.get("kind", "render") if m.get("app", {}).get("contract", 3) >= 6 else None


def job_network(m, j):
    """What a job may reach: a contract 6 render job nothing; a sync job its own `network` or the
    app's; before contract 6, the app's."""
    p = m.get("app", {})
    kind = job_kind(m, j)
    if kind == "render":
        return "none"
    if kind == "sync":
        return j.get("network", p.get("network", "none"))
    return p.get("network", "none")


def job_secrets(m, j):
    """The secrets a job gets: contract 6, its own `secrets` (render none); before 6, the app's
    `secrets` and `optional_secrets`, on every job."""
    if job_kind(m, j) is None:
        p = m.get("app", {})
        return list(p.get("secrets", [])) + list(p.get("optional_secrets", []))
    return list(j.get("secrets", [])) if job_kind(m, j) == "sync" else []


def contract6_errors(m, errs, warns):
    """[secrets], [auth], [artifacts] and the sync/render split (contract 6)."""
    p = m.get("app", {})
    jobs = m.get("job", [])
    secrets, auth, artifacts = m.get("secrets") or {}, m.get("auth") or {}, m.get("artifacts") or {}
    if p.get("contract", 3) < 6:
        for key in ("secrets", "auth", "artifacts"):
            if key in m:
                errs.append(f"[{key}] needs contract = 6")
        for j in jobs:
            for key in ("kind", "network", "secrets", "min_every"):
                if key in j:
                    errs.append(f"job {j['name']}: {key} needs contract = 6")
        return
    for key in ("secrets", "optional_secrets"):
        if p.get(key):
            errs.append(f"[app] {key}: contract 6 declares secrets as [secrets.<name>] and grants them "
                        "per job ([[job]] secrets), so a render job never gets one")
    for name, s in secrets.items():
        kind = s.get("kind", "value")
        if kind == "oauth":
            if "auth" not in s:
                errs.append(f"secret {name}: kind = \"oauth\" needs auth = \"<provider>\"")
            elif s["auth"] not in auth:
                errs.append(f"secret {name}: auth {s['auth']!r} isn't declared in [auth]")
        else:
            for key in ("auth", "multiple"):
                if key in s:
                    errs.append(f"secret {name}: {key} is for kind = \"oauth\"")
    used_auth = {s.get("auth") for s in secrets.values()}
    for prov in auth:
        if prov not in used_auth:
            warns.append(f"[auth.{prov}] isn't used by any oauth secret")
    used = set()
    for j in jobs:
        kind = job_kind(m, j)
        where = f"job {j['name']}"
        if j["name"] == "render" and kind != "render":
            errs.append("the job named 'render' is the planner's output job: it can't be kind = \"sync\"")
        if kind == "render":
            for key in ("secrets", "network"):
                if key in j:
                    errs.append(f"{where}: a render job can't declare {key} (it runs with neither; "
                                "fetch in a sync job and hand render an artifact)")
            if "min_every" in j:
                errs.append(f"{where}: min_every is for sync jobs")
        for s in j.get("secrets", []):
            used.add(s)
            if s not in secrets:
                errs.append(f"{where}: secret {s!r} isn't declared in [secrets]")
        if "min_every" in j and kind == "sync":
            if "every" not in j:
                errs.append(f"{where}: min_every needs every (the default cadence)")
            else:
                if minutes(j["min_every"]) < 5:
                    errs.append(f"{where}: min_every {j['min_every']} is under 5 minutes")
                if minutes(j["min_every"]) > minutes(j["every"]):
                    errs.append(f"{where}: min_every {j['min_every']} is longer than every {j['every']}")
    for name in secrets:
        if name not in used:
            warns.append(f"secret {name}: no job lists it in secrets, so no run gets it")
    if artifacts and not any(job_kind(m, j) == "sync" for j in jobs):
        errs.append("[artifacts] are written by sync jobs: declare a [[job]] with kind = \"sync\"")
    for name in artifacts:
        if not any(f"self:{name}" in j.get("inputs", []) for j in jobs if job_kind(m, j) == "render"):
            warns.append(f"artifact {name}: no render job lists \"self:{name}\" in inputs, so a new "
                         "artifact won't re-run render")


def rule_errors(m, app_dir=None):
    errs, warns = [], []
    p = m.get("app", {})
    jobs = [j["name"] for j in m.get("job", [])]
    feeds = {f["name"]: f for f in m.get("feed", [])}
    contract6_errors(m, errs, warns)

    for kind, names in (("job", jobs), ("feed", [f["name"] for f in m.get("feed", [])]),
                        ("example", [e["name"] for e in m.get("example", [])])):
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            errs.append(f"duplicate {kind} names: {sorted(dup)}")
    both = set(p.get("secrets", [])) & set(p.get("optional_secrets", []))
    if both:
        errs.append(f"secrets listed as both required and optional: {sorted(both)}")
    if feeds and "render" not in jobs:
        errs.append("an app with feeds needs a job named 'render' (the planner's output job)")
    if p.get("prompts") and "prompts" not in feeds:
        errs.append("prompts = true needs a [[feed]] named 'prompts'")
    if "prompts" in feeds and not p.get("prompts"):
        errs.append("a feed named 'prompts' needs prompts = true (the prompts grant)")
    if m.get("events", {}).get("accept") and "event" not in jobs:
        errs.append("[events] accept needs a job named 'event'")
    # Contract 5: a feed's ink sets. Slot feeds land on the board, in k4.
    for f in m.get("feed", []):
        inks = f.get("inks", ["k4"])
        if inks != ["k4"] and p.get("contract", 3) < 5:
            errs.append(f"feed {f['name']}: inks other than k4 need contract = 5")
        if f["size"] == "slot" and "k4" not in inks:
            errs.append(f"feed {f['name']}: a slot feed is drawn in the board's k4")
        if f["name"] == "prompts" and (f["size"] != "slot" or inks != ["k4"]):
            errs.append("the prompts feed is a k4 slot feed")
    # Contract 4: app UIs (a bundle and/or a backend), docs and job args.
    ui = m.get("ui")
    c4 = p.get("contract", 3) >= 4
    if not c4:
        if ui and ("entry" in ui or "backend" in ui):
            errs.append("[ui] entry and backend need contract = 4")
        if m.get("docs"):
            errs.append("[docs] needs contract = 4")
        if any(j.get("args") for j in m.get("job", [])):
            errs.append("job args need contract = 4")
    elif ui is not None:
        if "entry" not in ui and not ui.get("backend"):
            errs.append("[ui] needs an entry (the UI bundle), backend = true, or both")
        if any(c in (".", "..") for c in ui.get("entry", "").split("/")):
            errs.append(f"[ui] entry {ui['entry']!r} can't contain . or ..")
        if ui.get("entry") and not ui.get("backend") and ("idle_s" in ui or "start_timeout_s" in ui):
            warns.append("[ui] idle_s and start_timeout_s only apply to a backend")
    for name, d in m.get("docs", {}).items():
        for j in d.get("on_change", []):
            if j not in jobs:
                errs.append(f"doc {name}: on_change job {j!r} isn't declared")
    if m.get("docs") and not (ui or {}).get("entry"):
        warns.append("[docs] without a [ui] entry: only jobs can change them")
    for j in m.get("job", []):
        if "every" in j and "daily" in j:
            errs.append(f"job {j['name']}: every and daily are exclusive")
        if "jitter_s" in j and "every" not in j and "daily" not in j:
            errs.append(f"job {j['name']}: jitter_s without a schedule")
        if "every" in j and minutes(j["every"]) < 5:
            errs.append(f"job {j['name']}: every {j['every']} is under 5 minutes")
        for inp in j.get("inputs", []):
            src, _, name = inp.partition(":")
            if src == "self" and name not in p.get("exports", []) and name not in feeds \
                    and name not in (m.get("artifacts") or {}):
                warns.append(f"job {j['name']}: input {inp} is not an export, artifact or feed of this app")
    for name, st in m.get("settings", {}).items():
        t, d = st.get("type"), st.get("default")
        if t == "choice" and not st.get("choices"):
            errs.append(f"setting {name}: type choice needs choices")
        if "default" in st:
            ok = {"string": isinstance(d, str), "boolean": isinstance(d, bool),
                  "number": isinstance(d, (int, float)) and not isinstance(d, bool),
                  "integer": isinstance(d, int) and not isinstance(d, bool),
                  "choice": d in st.get("choices", [])}.get(t, True)
            if not ok:
                errs.append(f"setting {name}: default {d!r} is not a valid {t}")
            elif t in ("number", "integer") and not (st.get("min", d) <= d <= st.get("max", d)):
                errs.append(f"setting {name}: default {d} is outside min/max")
        if "min" in st and "max" in st and st["min"] > st["max"]:
            errs.append(f"setting {name}: min > max")
        if not st.get("optional") and "default" not in st:
            warns.append(f"setting {name}: required with no default (the app exits 5 until it is set)")
    if p.get("memory"):
        extra = mb(p.get("tmp", "0m") if p.get("tmp") else "0m") + p.get("cache", {}).get("tmpfs_mb", 0)
        if extra >= mb(p["memory"]):
            errs.append(f"tmp + cache tmpfs ({extra:g} MB) must fit inside memory ({p['memory']}): tmpfs is charged to it")
    for e in m.get("example", []):
        where = f"example {e['name']}"
        if app_dir is not None and not (app_dir / e["fixture"]).is_dir():
            errs.append(f"{where}: no directory {e['fixture']}")
        job = e.get("job", "render")
        if job not in jobs:
            errs.append(f"{where}: job {job!r} isn't declared")
        for f, surface in e.get("feeds", {}).items():
            if f not in feeds:
                errs.append(f"{where}: feed {f!r} isn't declared")
                continue
            size = feeds[f]["size"]
            if size != "slot" and not surface.startswith(size + "."):
                errs.append(f"{where}: feed {f} is fixed at {size}, example asks {surface}")
            ink = surface.rsplit(".", 1)[-1]
            if ink not in feeds[f].get("inks", ["k4"]):
                errs.append(f"{where}: feed {f} isn't drawn in {ink} (its inks: {', '.join(feeds[f].get('inks', ['k4']))})")
            if size == "slot" and surface not in SLOT_SURFACES:
                warns.append(f"{where}: {surface} is not a default slot surface ({', '.join(sorted(SLOT_SURFACES))})")
    if feeds and not m.get("example"):
        warns.append("no [[example]]: CI can't render this app in fixture mode")
    missing = [k for k in ("blurb", "about", "ink", "license", "repo") if k not in p]
    if missing:
        warns.append(f"[app] has no {', '.join(missing)}: the catalog page shows blanks for them")
    return errs, warns


def load(path):
    path = Path(path)
    if path.is_dir():
        path = path / "slowapp.toml"
    with open(path, "rb") as f:
        return path, tomllib.load(f)


def validate(path, schema=None):
    """-> (manifest dict, errors, warnings)."""
    schema = schema or json.loads(SCHEMA.read_text())
    try:
        path, m = load(path)
    except (OSError, tomllib.TOMLDecodeError) as e:
        return {}, [f"{path}: {e}"], []
    errs = schema_errors(m, schema, schema)
    if errs:                                     # cross-field rules assume the structure is right
        return m, errs, []
    e2, warns = rule_errors(m, path.parent)
    return m, e2, warns


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    targets = [Path(a) for a in argv] or [Path(".")]
    bad = 0
    for t in targets:
        _, errs, warns = validate(t)
        name = (t if t.is_dir() else t.parent).resolve().name
        for w in warns:
            print(f"warning {name}: {w}")
        for e in errs:
            print(f"error   {name}: {e}")
        print(f"{'ok' if not errs else 'FAIL':7} {name}")
        bad += bool(errs)
    return 1 if bad else 0

