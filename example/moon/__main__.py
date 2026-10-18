"""The moon app's entrypoint: `python3 -m moon job render` (the image's ENTRYPOINT and CMD).

Contract 4: the app's UI (ui/, built into /ui/index.html) edits the `note` doc, which the home
card shows, and asks the `phases` job for the coming quarters (`jobs.run("phases", {count})`)."""
from datetime import timedelta

import slowapp_kit as kit
from slowapp_kit import Card

from . import draw, phase


@kit.job("render")
def render(ctx):
    surface = ctx.feed("phase")
    if surface is None:
        return
    south = bool(ctx.settings.get("south"))
    t = ctx.for_
    ctx.write_feed("phase", [
        Card("home", draw.home(ctx, surface, south, ctx.doc("note")), phase.name(t),
             peek=f"{phase.illumination(t) * 100:.0f}% lit"),
        Card("week", draw.week(ctx, surface, south), "The week ahead"),
    ], valid_from=t, valid_until=t + timedelta(hours=6))


QUARTERS = [(0.0, "New moon"), (0.25, "First quarter"), (0.5, "Full moon"), (0.75, "Last quarter")]


@kit.job("phases")
def phases(ctx):
    """The next `count` quarters (1-24, default 8), for the UI: no feeds, just /out/result.json."""
    count = max(1, min(24, int(ctx.args.get("count", 8))))
    t, out = ctx.now, []
    while len(out) < count:
        frac, name = min(((f, n) for f, n in QUARTERS), key=lambda q: phase.next_phase(t, q[0]))
        at = phase.next_phase(t, frac).astimezone(ctx.tz)
        out.append({"name": name, "at": at.isoformat(timespec="minutes"), "day": f"{at:%a %d %b}"})
        t = at + timedelta(hours=1)
    ctx.result({"phases": out, "lit": round(phase.illumination(ctx.now), 3), "now": phase.name(ctx.now)})


kit.main()
