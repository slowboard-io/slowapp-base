"""The moon app's entrypoint: `python3 -m moon job render` (the image's ENTRYPOINT and CMD)."""
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
        Card("home", draw.home(ctx, surface, south), phase.name(t), peek=f"{phase.illumination(t) * 100:.0f}% lit"),
        Card("week", draw.week(ctx, surface, south), "The week ahead"),
    ], valid_from=t, valid_until=t + timedelta(hours=6))


kit.main()
