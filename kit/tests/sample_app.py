"""A tiny app for the kit tests: run as `sample_app.py job <name>` or imported. slowapp_kit comes
from PYTHONPATH, like a real app's."""
import json

from PIL import Image, ImageDraw

import slowapp_kit as kit
from slowapp_kit import RED, WHITE, Card


@kit.job("render")
def render(ctx):
    img = Image.new("RGB", (452, 444), WHITE)
    ImageDraw.Draw(img).rectangle((10, 10, 100, 60), fill=RED)
    ctx.write_feed("left", [Card("home", img, "Hi")])


@kit.job("flaky")
def flaky(ctx):
    raise kit.Transient("upstream down")


@kit.job("boom")
def boom(ctx):
    raise RuntimeError("bug")


@kit.job("env")
def env(ctx):
    """What a warm job actually sees, for the hub-request test."""
    kit.log("env job: hello from the child")
    kit.atomic_write(ctx.out / "env.json", json.dumps({
        "reason": ctx.reason, "run_id": ctx.run_id, "for": ctx.for_.isoformat(), "tz": str(ctx.tz),
        "deadline": ctx.deadline.isoformat() if ctx.deadline else None,
        "feeds": [s.name for s in ctx.feeds], "data": str(ctx.data)}))


@kit.job("event")
def event(ctx):
    kit.atomic_write(ctx.out / "events.json", json.dumps(ctx.events()))


if __name__ == "__main__":
    kit.main()
