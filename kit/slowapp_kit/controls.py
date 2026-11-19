"""Card controls (slowboard docs/CONTROLS.md): regions of a card with pre-rendered variants that a
board swaps in place as its keys change their values, without the app running on it.

    from slowapp_kit import Card, Control, Controls
    ctl = Controls(items=[Control("pills", "toggle", (0, 152, 480, 96), variants={...}, due=t,
                                  emit={"kind": "set", "data": {"task": "pills"}})],
                   focus=["pills"], keys={"key1.tap": ("activate", "Done"), "key2.tap": ("next", "Next")})
    write_feed(ctx, "today", [Card("home", body, "Today", controls=ctl)], ...)

Everything the hub checks at ingest is checked here first, so a mistake fails the app's tests:
the exact variant set for each kind, every variant exactly its rect's size and in the feed's inks,
ids, focus and keys, and on a 540 x 960 board, that no control lands in the board's own areas
(the app strip and the QR code to the app's page). `screens(card, surface)` composes the card with
each variant in turn, for a test that looks at every state a board can show.

The key hints are the app's to draw, where the keys are (KEY_Y). A deck draws them in its bodies; a
card with controls draws them as `label` controls, blank in their `none` variant (the keys asleep)
and saying what a tap does now in the others, so they come and go with the keys without a render.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

from PIL import Image

from .errors import ContractError
from .inks import InkError, encode_png

KINDS = ("toggle", "counter", "choice", "sum", "label")
FOCUSABLE = ("toggle", "counter", "choice")
ACTIONS = ("activate", "next", "prev", "card_next", "card_prev")
FOCUS_ACTIONS = ("activate", "next", "prev")
KEYS = ("key1.tap", "key2.tap")
STARTS = ("first", "first_open")
MAX_CONTROLS, MAX_VARIANTS, MAX_VALUE, MAX_APPLIED, MAX_LABEL = 16, 64, 15, 256, 12
NAME_RE = re.compile(r"^(?!\.)[A-Za-z0-9_.-]{1,48}$")

# The board's own areas on a 540 x 960 portrait glass, [x, y, w, h] (sb_proto::schedule::areas):
# the app strip, and a QR code to the app's page (on a card with controls). Draw nothing in them
# either: the board covers them.
BOARD_AREAS = {"strip": (0, 900, 540, 60), "qr": (16, 16, 120, 120)}

# The keys on that glass, for drawing their hints: on the right edge, K1 (black, a white square:
# key1, Done or Back) centred at y 200 and K2 (white, a black circle: key2, Next) at y 310.
KEY_Y = {"key1": 200, "key2": 310}


@dataclass
class Control:
    id: str
    kind: str
    rect: tuple                       # (x, y, w, h) on the card
    variants: dict                    # variant name -> PIL image of exactly (w, h)
    value: int = 0                    # the app's view of the value (derived kinds: 0)
    max: int | None = None            # counter, choice: 1-15
    wrap: bool = False
    of: list = field(default_factory=list)   # sum: the controls it adds up
    due: datetime | None = None       # focusable: the index time, never drawn
    emit: dict | None = None          # focusable: {"kind": ..., "data": {...}}, echoed in the event

    def top(self):
        return 1 if self.kind == "toggle" else (self.max or 0) if self.kind in ("counter", "choice") else 0


@dataclass
class Controls:
    items: list
    focus: list | None = None         # focusable control ids, in the order "next" visits them
    start: str = "first_open"
    keys: dict = field(default_factory=dict)   # "key1.tap" -> (action, label)
    period: str | None = None
    applied: list = field(default_factory=list)


def _bad(card, msg):
    raise ContractError(f"card {card} controls: {msg}")


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def variant_names(ctl, c):
    """The exact variant names the hub requires for control `c` of `ctl`."""
    if c.kind in FOCUSABLE:
        return {f"{n}{f}" for n in range(c.top() + 1) for f in ("", "f")}
    if c.kind == "sum":
        by = {x.id: x for x in ctl.items}
        return {str(n) for n in range(sum(by[i].top() for i in c.of) + 1)}
    # label: per focused control and value, exact or by kind; "none" when nothing has the focus.
    by = {x.id: x for x in ctl.items}
    want = set()
    for fid in ctl.focus or []:
        f = by[fid]
        for n in range(f.top() + 1):
            want.add(f"{f.kind}.{n}" if f"{f.kind}.{n}" in c.variants else f.kind)
    if not ctl.focus or "none" in c.variants:
        want.add("none")
    return want


def check(ctl, card, surface):
    """The hub's rules (sb_proto Controls::validate), plus the board's areas on a 540 x 960."""
    if not 1 <= len(ctl.items) <= MAX_CONTROLS:
        _bad(card, f"{len(ctl.items)} controls (1-{MAX_CONTROLS})")
    if len(ctl.applied) > MAX_APPLIED:
        _bad(card, f"{len(ctl.applied)} applied ids (at most {MAX_APPLIED})")
    total = sum(len(c.variants) for c in ctl.items)
    if total > MAX_VARIANTS:
        _bad(card, f"{total} variants (at most {MAX_VARIANTS} a card)")
    by = {}
    for c in ctl.items:
        if not NAME_RE.match(c.id) or c.id in by:
            _bad(card, f"control id {c.id!r} bad or repeated")
        if c.kind not in KINDS:
            _bad(card, f"{c.id}: kind {c.kind!r} (one of {', '.join(KINDS)})")
        by[c.id] = c
    if ctl.start not in STARTS:
        _bad(card, f"focus start {ctl.start!r}")
    for fid in ctl.focus or []:
        if fid not in by or by[fid].kind not in FOCUSABLE or (ctl.focus or []).count(fid) > 1:
            _bad(card, f"focus: {fid} isn't a focusable control or is repeated")
    for c in ctl.items:
        x, y, w, h = c.rect
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > surface.w or y + h > surface.h:
            _bad(card, f"{c.id}: rect {c.rect} isn't inside {surface.name}")
        if surface.inks == "k4" and (x % 4 or w % 4):
            _bad(card, f"{c.id}: k4 x and w must be multiples of 4")
        if (surface.w, surface.h) == (540, 960):
            for name, area in BOARD_AREAS.items():
                if _overlap(c.rect, area):
                    _bad(card, f"{c.id}: rect {c.rect} overlaps the board's {name} {area}")
        if c.kind in FOCUSABLE:
            if c.kind == "toggle" and c.max not in (None, 1):
                _bad(card, f"{c.id}: a toggle's max is 1")
            if c.kind != "toggle" and not (c.max and 1 <= c.max <= MAX_VALUE):
                _bad(card, f"{c.id}: max must be 1-{MAX_VALUE}")
            if not 0 <= c.value <= c.top():
                _bad(card, f"{c.id}: value {c.value} isn't 0-{c.top()}")
            if c.of:
                _bad(card, f"{c.id}: only a sum has `of`")
            if not (c.emit or {}).get("kind"):
                _bad(card, f"{c.id}: emit needs a kind")
            if c.due is not None and c.due.tzinfo is None:
                _bad(card, f"{c.id}: due has no offset")
        else:
            if c.value or c.max is not None or c.wrap or c.due is not None:
                _bad(card, f"{c.id}: a {c.kind} has no value, max, wrap or due")
            if c.kind == "sum":
                if not c.of:
                    _bad(card, f"{c.id}: a sum needs `of`")
                for t in c.of:
                    if t not in by or by[t].kind not in FOCUSABLE or c.of.count(t) > 1:
                        _bad(card, f"{c.id}: sums {t!r}, which isn't a focusable control or is repeated")
        want, have = variant_names(ctl, c), set(c.variants)
        if want != have:
            _bad(card, f"{c.id} ({c.kind}): variants missing {sorted(want - have)}, unexpected {sorted(have - want)}")
        for name, img in c.variants.items():
            if img.size != (w, h):
                _bad(card, f"{c.id}/{name}: {img.size[0]}x{img.size[1]}, the rect is {w}x{h}")
    for k, b in ctl.keys.items():
        if k not in KEYS:
            _bad(card, f"key {k!r}: only {', '.join(KEYS)} (holds move between apps)")
        action, label = b
        if action not in ACTIONS:
            _bad(card, f"{k}: action {action!r} (one of {', '.join(ACTIONS)})")
        if not label or len(label) > MAX_LABEL or any(ch < " " for ch in label):
            _bad(card, f"{k}: label {label!r} (1-{MAX_LABEL} characters)")
        if action in FOCUS_ACTIONS and not ctl.focus:
            _bad(card, f"{k} acts on the focus, but nothing can have it")


def write(ctl, card, surface, root, atomic_write):
    """Checks `ctl`, writes every variant to `<root>/controls/<card>/<control>/<name>.png`, and
    returns the deck's `controls` object."""
    check(ctl, card, surface)
    items = []
    for c in ctl.items:
        paths = {}
        for name, img in sorted(c.variants.items()):
            rel = f"controls/{card}/{c.id}/{name}.png"
            try:
                png = encode_png(img, surface.inks)
            except InkError as e:
                raise ContractError(f"card {card} control {c.id}/{name}: {e}")
            atomic_write(root / rel, png)
            paths[name] = rel
        item = {"id": c.id, "kind": c.kind, "rect": list(c.rect), "variants": paths}
        if c.value:
            item["value"] = c.value
        if c.max is not None:
            item["max"] = c.max
        if c.wrap:
            item["wrap"] = True
        if c.of:
            item["of"] = list(c.of)
        if c.due is not None:
            item["due"] = c.due.isoformat(timespec="seconds")
        if c.emit:
            item["emit"] = c.emit
        items.append(item)
    out = {"items": items}
    if ctl.period:
        out["period"] = ctl.period
    if ctl.applied:
        out["applied"] = list(ctl.applied)
    if ctl.focus:
        out["focus"] = {"order": list(ctl.focus), "start": ctl.start}
    if ctl.keys:
        out["keys"] = {k: {"do": a, "label": lbl} for k, (a, lbl) in ctl.keys.items()}
    return out


def shown(ctl, values=None, focus=None):
    """The variant each control shows for `values` (id -> value; missing: the card's own) with the
    highlight on `focus` (None: keys off): [(control, variant name)]. The same choice as the hub's
    preview and the board (sb_proto Controls::shown)."""
    values = values or {}
    by = {c.id: c for c in ctl.items}
    val = lambda c: min(values.get(c.id, c.value), c.top())  # noqa: E731
    f = by.get(focus) if focus in by and by[focus].kind in FOCUSABLE else None
    out = []
    for c in ctl.items:
        if c.kind in FOCUSABLE:
            name = f"{val(c)}{'f' if f is c else ''}"
        elif c.kind == "sum":
            name = str(sum(val(by[t]) for t in c.of))
        else:
            name = "none" if f is None else (f"{f.kind}.{val(f)}" if f"{f.kind}.{val(f)}" in c.variants else f.kind)
        if name in c.variants:
            out.append((c, name))
    return out


def compose(body, ctl, values=None, focus=None):
    """The card as a board shows it for `values` and `focus`."""
    img = body.copy()
    for c, name in shown(ctl, values, focus):
        img.paste(c.variants[name], c.rect[:2])
    return img


def screens(card):
    """Every state worth looking at in a test: the card as drawn, then each control's every variant
    on its own (the others as drawn), as [(name, image)]. A clipped label or a variant that
    doesn't line up with its row shows here, not on the glass."""
    ctl = card.controls
    out = [("as-drawn", compose(card.image, ctl))]
    for c in ctl.items:
        for name, v in sorted(c.variants.items()):
            img = compose(card.image, ctl)
            img.paste(v, c.rect[:2])
            out.append((f"{c.id}.{name}", img))
    return out
