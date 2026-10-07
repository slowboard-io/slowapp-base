"""Writers for /out (docs/SLOWBOARD.md §8.6). Every card goes through the ink and size check here,
so an app can't hand the hub something it will reject.

  /out/feeds/<feed>/deck.json + cards/<id>.png
  /out/prompts.json + prompts/<instance>/<binding>.png      (prompts grant)
  /out/summary.json, /out/cache_key, /out/timing.json
"""
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from PIL import Image

from .errors import ContractError
from .inks import InkError, encode_png

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
PROMPT_ID_RE = re.compile(r"^(?!\.)[A-Za-z0-9_.@:+-]{1,96}$")      # slowbhub ingest's safe_name
MAX_CARDS, MAX_PROMPTS = 32, 8
BINDINGS = ("own.tap", "spare.tap", "own.hold", "spare.hold")
KINDS = ("home", "detail")


def atomic_write(path, data, mode=0o644):
    """tmp, fsync, rename, fsync the directory. str is written as UTF-8."""
    path = os.fspath(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        f.write(data.encode() if isinstance(data, str) else data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _json(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False, default=_default) + "\n"


def _default(v):
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    raise TypeError(f"{type(v).__name__} is not JSON serialisable")


def _iso(t):
    if t is None:
        return None
    if isinstance(t, str):
        t = datetime.fromisoformat(t)
    if t.tzinfo is None:
        raise ContractError(f"time {t} has no offset: /out times are RFC 3339 with an offset")
    return t.isoformat(timespec="seconds")


@dataclass
class Card:
    id: str
    image: Image.Image
    title: str
    peek: str = ""
    kind: str = ""                 # "" -> home for the first card, detail for the rest
    keep_s: int | None = None
    extra: dict = field(default_factory=dict)


def write_feed(ctx, feed, cards, valid_from=None, valid_until=None):
    """Write one feed's deck. `cards` is a list of Card (home first). valid_from defaults to now;
    valid_until defaults to now + 1 h. Returns the deck dict."""
    surface = ctx.feed(feed)
    if surface is None:
        raise ContractError(f"feed {feed!r} wasn't requested in SLOWAPP_FEEDS")
    if not cards or len(cards) > MAX_CARDS:
        raise ContractError(f"{feed}: {len(cards)} cards (1-{MAX_CARDS})")
    root = ctx.out / "feeds" / feed
    seen, deck = set(), []
    for i, c in enumerate(cards):
        if not ID_RE.match(c.id) or c.id in seen:
            raise ContractError(f"{feed}: card id {c.id!r} is not unique [a-z0-9][a-z0-9_-]*")
        seen.add(c.id)
        kind = c.kind or ("home" if i == 0 else "detail")
        if kind not in KINDS or (i == 0) != (kind == "home"):
            raise ContractError(f"{feed}/{c.id}: kind {kind!r} (the first card, and only it, is home)")
        if not c.title:
            raise ContractError(f"{feed}/{c.id}: a card needs a title")
        if c.image.size != (surface.w, surface.h):
            raise ContractError(f"{feed}/{c.id}: {c.image.size[0]}x{c.image.size[1]}, the surface is {surface.name}")
        try:
            png = encode_png(c.image, surface.inks)
        except InkError as e:
            raise ContractError(f"{feed}/{c.id}: {e}")
        atomic_write(root / "cards" / f"{c.id}.png", png)
        entry = dict(c.extra, id=c.id, title=c.title, peek=c.peek, kind=kind)
        if c.keep_s is not None:
            entry["keep_s"] = int(c.keep_s)
        deck.append(entry)
    vf = valid_from or ctx.now
    vu = valid_until or (ctx.now + timedelta(hours=1))
    doc = {"cards": deck, "surface": surface.name, "valid_from": _iso(vf), "valid_until": _iso(vu)}
    if datetime.fromisoformat(doc["valid_until"]) <= datetime.fromisoformat(doc["valid_from"]):
        raise ContractError(f"{feed}: valid_until is not after valid_from")
    atomic_write(root / "deck.json", _json(doc))
    return doc


def write_prompts(ctx, prompts, surface_feed="prompts"):
    """prompts: [{"id", "group", "slot_hint", "from", "until", "question",
                  "bindings": {"own.tap": {"image": Image, "strip": str, "emit": {...}}, ...}}].

    Checked here so an app fails in CI rather than at ingest or on the device (§4.3, E5): the
    manifest grants prompts; id is the hub's safe name ([A-Za-z0-9_.@:+-], <= 96, no leading dot;
    instance ids are rid@occurrence@ask_from); group and question are set; until > from; one to
    four known bindings, each a body at the prompt surface."""
    if not ctx.manifest.get("app", {}).get("prompts"):
        raise ContractError("write_prompts needs prompts = true in slowapp.toml (the prompts grant)")
    if len(prompts) > MAX_PROMPTS:
        raise ContractError(f"{len(prompts)} prompts (at most {MAX_PROMPTS})")
    surface = ctx.feed(surface_feed)
    if surface is None:
        raise ContractError(f"prompt feed {surface_feed!r} wasn't requested in SLOWAPP_FEEDS")
    out, seen = [], set()
    for p in prompts:
        pid = p.get("id")
        if not isinstance(pid, str) or not PROMPT_ID_RE.match(pid) or pid in seen:
            raise ContractError(f"prompt id {pid!r}: unique, [A-Za-z0-9_.@:+-], at most 96, no leading dot")
        seen.add(pid)
        missing = [k for k in ("group", "question", "from", "until", "bindings") if not p.get(k)]
        if missing:
            raise ContractError(f"{pid}: missing {', '.join(missing)}")
        entry = {k: p[k] for k in ("id", "group", "slot_hint", "question") if k in p}
        entry["from"], entry["until"] = _iso(p["from"]), _iso(p["until"])
        if datetime.fromisoformat(entry["until"]) <= datetime.fromisoformat(entry["from"]):
            raise ContractError(f"{pid}: until is not after from")
        if not isinstance(p["bindings"], dict) or len(p["bindings"]) > len(BINDINGS):
            raise ContractError(f"{pid}: bindings must map one to four of {', '.join(BINDINGS)}")
        entry["bindings"] = {}
        for name, b in p["bindings"].items():
            if name not in BINDINGS:
                raise ContractError(f"{pid}: unknown binding {name!r}")
            img = b.get("image") if isinstance(b, dict) else None
            if img is None or img.size != (surface.w, surface.h):
                raise ContractError(f"{pid}/{name}: binding body is not {surface.name}")
            try:
                png = encode_png(img, surface.inks)
            except InkError as e:
                raise ContractError(f"{pid}/{name}: {e}")
            rel = f"prompts/{pid}/{name}.png"
            atomic_write(ctx.out / rel, png)
            entry["bindings"][name] = {"show": rel, "strip": b.get("strip", ""), "emit": b.get("emit", {})}
        out.append(entry)
    atomic_write(ctx.out / "prompts.json", _json({"surface": surface.name, "prompts": out}))


def write_summary(ctx, status="ok", lines=(), actions=()):
    """The shell card (E7): {status, lines[], actions:[{label, job}]}. Any job may write it."""
    acts = [dict(a) for a in actions]
    for a in acts:
        if set(a) != {"label", "job"}:
            raise ContractError(f"summary action {a} needs exactly label and job")
    atomic_write(ctx.out / "summary.json", _json({"status": status, "lines": list(lines), "actions": acts}))


def write_cache_key(ctx, key):
    atomic_write(ctx.out / "cache_key", str(key) + "\n")


def write_timing(ctx, next_change_at):
    atomic_write(ctx.out / "timing.json", _json({"next_change_at": _iso(next_change_at)}))
