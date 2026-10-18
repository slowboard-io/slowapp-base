"""slowapp_kit: the app side of contracts 3 to 5 (see MANIFEST.md and the hub's docs/SLOWBOARD.md §8).

An app is a container whose command is `job <name>` or `serve`. It reads its run from the
environment (SLOWAPP_*), draws each requested feed at its surface size in the four inks, and
writes /out. The kit does the parts every app would otherwise get wrong:

    from slowapp_kit import Card, job, main

    @job("render")
    def render(ctx):
        vic = ctx.fetch("victoria.json", lambda: ctx.http_json(URL))   # fetch first...
        ctx.exit_if_unchanged()                                         # ...exit 3 if nothing moved
        for s in ctx.feeds:                                             # ...then draw
            img = ctx.canvas(s)
            ...
            ctx.write_feed(s.feed, [Card("home", img, title="Today", peek="17° cloudy")])
        ctx.write_summary("ok", ["17° cloudy"])

    if __name__ == "__main__":
        main()

Contract 4 (app UIs): ctx.args (/in/args.json from the UI's jobs.run), ctx.docs and
ctx.doc(name) (the hub-stored docs, /in/docs), ctx.write_doc(name, value) (/out/docs, applied if
the doc didn't change meanwhile) and ctx.result(value) (/out/result.json, back to the UI).

Contract 5 (feeds for other glass): a feed may declare `inks = ["g16"]` and a fixed size, and the
hub runs the render job once per device that needs it. ctx.device is that device (id, profile,
w, h, inks; None in fixture mode) and ctx.feeds holds only its feeds, so draw what's asked for:

    for s in ctx.feeds:
        if s.inks == "g16":                       # a greyscale sleep screen
            img = snap_g16(draw_today(s.w, s.h))  # or grey(level) colours throughout
        ...

What it covers: the ink check and exact-size check on every card; blob ids (for tests); secret()
that honours fixture mode; fetch-then-draw snapshots that double as fixtures; an HTTP helper that
fits the deadline; /out/.metrics.json; one handler serving both the CLI and the warm UI; and BLAS
threads pinned to 1 (set before numpy can be imported through the kit).
"""
import os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")        # resources item 8; the base image sets them too

import sys  # noqa: E402

from PIL import ImageFont  # noqa: E402

from . import net, output  # noqa: E402
from .context import Context, Device, Surface, load_manifest  # noqa: E402
from .errors import (EXIT_CONTRACT, EXIT_NEEDS_CONFIG, EXIT_OK, EXIT_TRANSIENT, EXIT_UNCHANGED,  # noqa: E402
                     ContractError, JobExit, NeedsConfig, Transient, Unchanged)
from .inks import (BLACK, GREYS, INK_SETS, INKS, PALETTE, RED, WHITE, YELLOW, InkError, blob_id,  # noqa: E402
                   check_inks, check_png, encode_png, grey, pack_rows, snap_g16, to_indexed)
from .jobs import JOBS, execute, job, main, run_in_child  # noqa: E402
from .output import Card, atomic_write  # noqa: E402
from .serve import route  # noqa: E402

# The run context's verbs, so a job reads as ctx.write_feed(...), ctx.secret(...), ctx.fetch(...)
Context.write_feed = output.write_feed
Context.write_prompts = output.write_prompts
Context.write_summary = output.write_summary
Context.write_cache_key = output.write_cache_key
Context.write_timing = output.write_timing
Context.write_doc = output.write_doc
Context.result = output.write_result
Context.secret = net.secret
Context.http_get = net.http_get
Context.http_json = net.http_json
Context.fetch = net.fetch
Context.exit_if_unchanged = net.exit_if_unchanged

FONTS = os.environ.get("SLOWAPP_FONTS", "/opt/slowapp/fonts")


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def secret(name, optional=False, ctx=None):
    """Module-level form of ctx.secret, for code that has no context handy."""
    return net.secret(ctx or Context.from_env(), name, optional)


__all__ = [
    "BLACK", "WHITE", "YELLOW", "RED", "INKS", "PALETTE", "GREYS", "INK_SETS", "Card", "Context",
    "Device", "Surface", "JOBS", "grey", "snap_g16",
    "EXIT_OK", "EXIT_UNCHANGED", "EXIT_TRANSIENT", "EXIT_NEEDS_CONFIG", "EXIT_CONTRACT",
    "ContractError", "InkError", "JobExit", "NeedsConfig", "Transient", "Unchanged",
    "atomic_write", "blob_id", "check_inks", "check_png", "encode_png", "execute", "font", "job",
    "load_manifest", "log", "main", "pack_rows", "route", "run_in_child", "secret", "to_indexed",
]
