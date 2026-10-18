"""Secrets, HTTP and the fetch-then-draw convention (docs/SLOWBOARD.md §8.5, arch item 12).

Fetch-then-draw: a job gets every upstream input through ctx.fetch(name, fn) before it draws.

  live     fn() runs, its result is snapshotted to /data/snapshots/<name> and hashed.
  fixture  fn() never runs: the snapshot is read back from the fixture (/data/snapshots/<name>,
           or /data/<name>). So a live run's snapshots directory *is* a fixture.

After fetching, ctx.exit_if_unchanged() exits 3 when every snapshot hashes the same as the last
successful run (and the settings haven't changed); the kit stores the hash when a job exits 0.
"""
import hashlib
import json
import os
import socket
import urllib.error
import urllib.request

from .errors import ContractError, NeedsConfig, Transient, Unchanged
from .output import atomic_write

DEADLINE_MARGIN_S = 5        # leave this long to draw and write after the last fetch


def secret(ctx, name, optional=False):
    """A podman secret from /run/secrets/<name>. In fixture mode no secrets are mounted, so it
    returns a placeholder; missing in live mode means exit 5 (needs config), unless optional."""
    if ctx.fixture:
        return f"fixture-{name}"
    try:
        return (ctx.secrets_dir / name).read_text().strip()
    except FileNotFoundError:
        if optional:
            return None
        raise NeedsConfig(f"secret {name!r} is not set (slowbhub app secret set {ctx.app} {name})")


def http_get(ctx, url, timeout=60, headers=None):
    """GET url -> bytes. The timeout is capped to fit the job deadline (L7). Network failures are
    Transient (exit 4); 401 / 403 are NeedsConfig (exit 5). Fixture mode refuses the network."""
    if ctx.fixture:
        raise ContractError(f"network use in fixture mode: {url} (fetch it through ctx.fetch and ship a snapshot)")
    left = ctx.remaining()
    if left is not None:
        timeout = min(timeout, left - DEADLINE_MARGIN_S)
        if timeout <= 0:
            raise Transient(f"no time left before the deadline for {url}")
    req = urllib.request.Request(url, headers=dict({"User-Agent": f"slowapp/{ctx.app}"}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise NeedsConfig(f"{url}: HTTP {e.code}")
        raise Transient(f"{url}: HTTP {e.code}")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise Transient(f"{url}: {e}")


def http_json(ctx, url, timeout=60, headers=None):
    try:
        return json.loads(http_get(ctx, url, timeout, headers))
    except ValueError as e:
        raise Transient(f"{url}: not JSON ({e})")


def _encode(name, value):
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if name.endswith(".json"):
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if isinstance(value, str):
        return value.encode()
    raise ContractError(f"snapshot {name}: return bytes, str, or JSON for a .json name")


def _decode(name, data):
    return json.loads(data) if name.endswith(".json") else data


def snapshot_dir(ctx):
    return ctx.data / "snapshots"


def fetch(ctx, name, fn):
    """Fetch one upstream input (see the module docstring). `name` is a file name such as
    "victoria.json"; .json results are stored as JSON, anything else as bytes."""
    if "/" in name or name.startswith("."):
        raise ContractError(f"snapshot name {name!r}")
    if ctx.fixture:
        for p in (snapshot_dir(ctx) / name, ctx.data / name):
            if p.exists():
                data = p.read_bytes()
                break
        else:
            raise ContractError(f"fixture has no snapshot {name!r}")
    else:
        data = _encode(name, fn())
        try:
            atomic_write(snapshot_dir(ctx) / name, data)
        except OSError:
            pass                      # read-only /data: the snapshot is only a convenience
    ctx._fetched[name] = hashlib.sha256(data).hexdigest()
    return _decode(name, data)


def snapshot_hash(ctx):
    h = hashlib.sha256()
    for name in sorted(ctx._fetched):
        h.update(f"{name}={ctx._fetched[name]}\n".encode())
    h.update(json.dumps(ctx.settings, sort_keys=True).encode())
    if ctx.device:
        # Contract 5: each device's run draws its own feeds, so the same upstream data is new to it.
        h.update(f"device={ctx.device.id}\n".encode())
    return h.hexdigest()


def _hash_path(ctx):
    # One per device (contract 5), so the board's run doesn't make the sleep screen's look unchanged.
    dev = f".{ctx.device.id}" if ctx.device else ""
    return snapshot_dir(ctx) / f".{ctx.job}{dev}.hash"


def exit_if_unchanged(ctx):
    """Exit 3 when nothing fetched has changed since the last successful run of this job."""
    if not ctx._fetched or ctx.fixture:
        return
    try:
        last = _hash_path(ctx).read_text().strip()
    except FileNotFoundError:
        return
    if last == snapshot_hash(ctx):
        raise Unchanged("upstream data unchanged")


def remember(ctx):
    """Called by the kit after a job exits 0: store the snapshot hash and write /out/cache_key."""
    if not ctx._fetched:
        return
    key = snapshot_hash(ctx)
    if not (ctx.out / "cache_key").exists():
        atomic_write(ctx.out / "cache_key", key + "\n")
    if not ctx.fixture:
        try:
            atomic_write(_hash_path(ctx), key + "\n")
        except OSError:
            pass
