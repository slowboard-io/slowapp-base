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


@kit.job("remote")
def remote(ctx):
    """A cloud hub run's job (test_remote): reads /in and /data, writes /out, /data and /cache, and
    exits as /in/settings.json says."""
    print("remote job: to stdout", flush=True)
    kit.log("remote job: to stderr")
    s = ctx.settings
    count = ctx.data / "count.txt"
    n = int(count.read_text()) + 1 if count.exists() else 1
    count.write_text(str(n))
    if s.get("big_kb"):
        (ctx.data / "big.bin").write_bytes(b"x" * (s["big_kb"] * 1024))
    (ctx.cache / "scratch").write_text("cache")
    if s.get("sleep"):
        import signal
        import time
        if s.get("ignore_term"):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print("remote job: sleeping", flush=True)
        time.sleep(s["sleep"])
    img = Image.new("RGB", (452, 444), WHITE)
    ctx.write_feed("left", [Card("home", img, "Hi")])
    import os
    kit.atomic_write(ctx.out / "seen.json", json.dumps({
        "settings": s, "docs": ctx.docs, "count": n, "in": str(ctx.inp), "data": str(ctx.data),
        "cache": str(ctx.cache), "remote_env": sorted(k for k in os.environ if k.startswith("SLOWAPP_REMOTE"))}))
    if s.get("exit") == 3:
        raise kit.Unchanged("same")
    if s.get("exit") == 5:
        raise kit.NeedsConfig("no key")
    if s.get("exit") == 1:
        raise RuntimeError("bug")


@kit.job("net")
def net(ctx):
    """What network a remote job has (test_remote): its interfaces, and whether it reaches the
    store the test runs (SLOWAPP_TEST_REACH, host:port)."""
    import os
    import socket
    host, port = os.environ["SLOWAPP_TEST_REACH"].split(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
        reach = True
    except OSError as e:
        reach = f"{type(e).__name__}: {e}"
    try:
        with open("/proc/net/route") as f:                  # the IPv4 routes, past the header
            routes = [line.split()[0] for line in f.readlines()[1:] if line.strip()]
    except OSError:
        routes = None
    print("net job: done", flush=True)
    kit.atomic_write(ctx.out / "net.json", json.dumps({
        "ifaces": sorted(n for _, n in socket.if_nameindex()), "reach": reach, "routes": routes,
        "key_file": os.environ.get("SLOWAPP_REMOTE_KEY_FILE"),
        "key_file_exists": bool(os.environ.get("SLOWAPP_TEST_KEY_PATH")) and os.path.exists(os.environ["SLOWAPP_TEST_KEY_PATH"])}))


if __name__ == "__main__":
    kit.main()
