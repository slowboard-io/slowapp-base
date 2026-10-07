"""One handler, two transports (docs/SLOWBOARD.md §8.5, arch item 11, resources item 2, M10).

    from slowapp_kit import job, main

    @job("render")
    def render(ctx):
        ...

    if __name__ == "__main__":
        main()          # argv: `job <name>` (attached CLI run) or `serve` (lazy UI on /run/sb/ui.sock)

CLI: the handler runs in-process and its outcome becomes the exit code. HTTP (warm UI): the same
handler runs in a child process (the app's own entrypoint, `job <name>`), so the UI doesn't keep
the job's heap, under a per-app job lock;
the reply is {"exit": 0|3|4|5|64, "message": "..."} once the job has finished.
"""
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback

from . import metrics, net, uilog
from .context import Context
from .errors import EXIT_CONTRACT, EXIT_OK, ContractError, JobExit

JOBS = {}
LOCK_PATH = os.environ.get("SLOWAPP_JOB_LOCK", "/tmp/.sb-job.lock")


def job(name):
    """Register a job handler: fn(ctx) -> None. Raise Unchanged / Transient / NeedsConfig for 3 / 4 / 5."""
    def deco(fn):
        JOBS[name] = fn
        return fn
    return deco


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def execute(name, ctx, transport="cli"):
    """Run one job against ctx. Returns (exit code, message). Never raises."""
    started = time.monotonic()
    code, msg = EXIT_OK, "ok"
    try:
        fn = JOBS.get(name)
        if fn is None:
            raise ContractError(f"no job {name!r} (have: {', '.join(sorted(JOBS)) or 'none'})")
        fn(ctx)
        net.remember(ctx)
    except JobExit as e:
        code, msg = e.code, str(e) or type(e).__name__
    except Exception as e:                         # noqa: BLE001 - a bug in the app: exit 1, with the trace
        traceback.print_exc()
        code, msg = 1, f"{type(e).__name__}: {e}"
    if code not in (EXIT_OK, 3):
        log(f"{ctx.app}/{name}: exit {code}: {msg}")
    metrics.write(ctx.out, started, code, transport, msg)
    return code, msg


class job_lock:
    """flock on a file in /tmp: one job at a time per app. The UI takes it around its child, which
    then skips it (SLOWAPP_JOB_LOCK_HELD); a CLI run takes it itself."""
    def __init__(self, inherit=False):
        self.skip = not inherit and os.environ.get("SLOWAPP_JOB_LOCK_HELD") == "1"

    def __enter__(self):
        if not self.skip:
            self.f = open(os.environ.get("SLOWAPP_JOB_LOCK", LOCK_PATH), "a")
            fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if not self.skip:
            fcntl.flock(self.f, fcntl.LOCK_UN)
            self.f.close()


def entrypoint():
    """argv that starts this app again: SLOWAPP_ENTRYPOINT (JSON list) or how we were launched."""
    if os.environ.get("SLOWAPP_ENTRYPOINT"):
        return json.loads(os.environ["SLOWAPP_ENTRYPOINT"])
    spec = getattr(sys.modules["__main__"], "__spec__", None)
    if spec is not None and spec.name:
        return [sys.executable, "-m", spec.name.removesuffix(".__main__")]
    return [sys.executable, os.path.abspath(sys.argv[0])]


def run_in_child(name, env=None, out=None, events_body=None, timeout=None):
    """Run a job as a child process (the HTTP transport): the app's own entrypoint with
    `job <name>`, so the UI never holds the job's heap. Returns (exit code, message)."""
    child_env = dict(os.environ, **(env or {}))
    if out:
        child_env["SLOWAPP_OUT"] = os.fspath(out)
        os.makedirs(out, exist_ok=True)
    tmp = None
    if events_body is not None:
        fd, tmp = tempfile.mkstemp(prefix="sb-events-", suffix=".jsonl")
        with os.fdopen(fd, "wb") as f:
            f.write(events_body)
        child_env["SLOWAPP_EVENTS_FILE"] = tmp
    try:
        with job_lock(inherit=True):
            child_env.update(SLOWAPP_JOB_LOCK_HELD="1", SLOWAPP_TRANSPORT="http")
            ring = uilog.active()
            p = subprocess.Popen(entrypoint() + ["job", name], env=child_env, stdin=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE if ring else None)
            pumping = uilog.pump(p.stderr) if ring else None
            try:
                p.wait(timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                return 137, "killed: job timed out"
            finally:
                if pumping:
                    pumping.join(5)
    finally:
        if tmp:
            os.unlink(tmp)
    code = p.returncode if p.returncode >= 0 else 128 - p.returncode
    try:
        with open(os.path.join(child_env.get("SLOWAPP_OUT", "/out"), ".metrics.json")) as f:
            msg = json.load(f).get("message", "")
    except (OSError, ValueError):
        msg = f"job exited {code} without metrics"
    return code, msg


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["job"] and len(argv) == 2:
        try:
            ctx = Context.from_env(job=argv[1])
        except JobExit as e:
            log(f"contract: {e}")
            sys.exit(e.code)
        with job_lock():
            code, _ = execute(argv[1], ctx, os.environ.get("SLOWAPP_TRANSPORT", "cli"))
        sys.exit(code)
    if argv == ["serve"]:
        from .serve import serve
        serve()
        return
    log("usage: job <name> | serve")
    sys.exit(EXIT_CONTRACT)
