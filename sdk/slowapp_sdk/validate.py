"""Validate an app manifest (slowapp.toml) against contract 3.

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


def rule_errors(m, app_dir=None):
    errs, warns = [], []
    p = m.get("app", {})
    jobs = [j["name"] for j in m.get("job", [])]
    feeds = {f["name"]: f for f in m.get("feed", [])}

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
    for j in m.get("job", []):
        if "every" in j and "daily" in j:
            errs.append(f"job {j['name']}: every and daily are exclusive")
        if "jitter_s" in j and "every" not in j and "daily" not in j:
            errs.append(f"job {j['name']}: jitter_s without a schedule")
        if "every" in j:
            minutes = int(j["every"][:-1]) * (60 if j["every"].endswith("h") else 1)
            if minutes < 5:
                errs.append(f"job {j['name']}: every {j['every']} is under 5 minutes")
        for inp in j.get("inputs", []):
            src, _, name = inp.partition(":")
            if src == "self" and name not in p.get("exports", []) and name not in feeds:
                warns.append(f"job {j['name']}: input {inp} is not an export or feed of this app")
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
            if size == "slot" and surface not in SLOT_SURFACES:
                warns.append(f"{where}: {surface} is not a default slot surface ({', '.join(sorted(SLOT_SURFACES))})")
    if feeds and not m.get("example"):
        warns.append("no [[example]]: CI can't render this app in fixture mode")
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

