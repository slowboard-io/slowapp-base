"""slowapp-remote: one job on a throwaway machine (the cloud hub's Fly Machines), its /in, /out and
/data carried by presigned links instead of mounts. MANIFEST.md, "Remote runs", is the contract.

    slowapp-remote job <name>

The hub keeps the image's ENTRYPOINT and sets the command to `slowapp-remote job <name>`: a kit app
sees that as its argv and lands here (jobs.main), and the job child is the app's own entrypoint with
`job <name>`. An image with no ENTRYPOINT runs /usr/local/bin/slowapp-remote, which needs the app's
command as SLOWAPP_ENTRYPOINT (a JSON list).

The wrapper fetches in.tar (and the board's saved data.tar.gz), runs the job as a child with
SLOWAPP_IN/OUT/STATE/CACHE pointed at local directories, then always tries to upload out.tar (with
the kit's .metrics.json and the wrapper's .remote.json), the new /data and the log tail.

Standard library only: the base images gain no dependency.
"""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .errors import EXIT_CONTRACT, EXIT_TRANSIENT

LOG_TAIL = 64 * 1024
HTTP_TIMEOUT_S = 60
ATTEMPTS = 3
# Seconds before the first retry, doubling after; the tests set it to 0.
RETRY_S = float(os.environ.get("SLOWAPP_REMOTE_RETRY_S", "2"))
TYPES = {"out": "application/x-tar", "data": "application/gzip", "log": "text/plain; charset=utf-8"}


class Unsafe(Exception):
    """A tar member that would land outside its directory, or isn't a plain file, dir or link."""


class Log:
    """The run's combined output: streamed to our stdout (the machine's log) and its last 64 KiB
    kept for the log upload."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stdout.buffer
        self.buf = bytearray()
        self.lock = threading.Lock()

    def write(self, b):
        with self.lock:
            try:
                self.stream.write(b)
                self.stream.flush()
            except (OSError, ValueError):
                pass
            self.buf += b
            if len(self.buf) > LOG_TAIL:
                del self.buf[:len(self.buf) - LOG_TAIL]

    def say(self, msg):
        self.write(f"slowapp-remote: {msg}\n".encode())

    def tail(self):
        with self.lock:
            return bytes(self.buf)


def _now():
    return datetime.now(timezone.utc)


def _iso(t):
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ------------------------------------------------------------------ HTTP (presigned links)

def _retryable(e):
    if isinstance(e, urllib.error.HTTPError):
        return e.code >= 500 or e.code in (408, 429)
    return not isinstance(e, ValueError)        # a bad link isn't retried; refused, reset, DNS, timeout are


def _attempts(what, log, fn):
    """fn() with retries on network errors and 5xx. Returns fn's value; raises the last error."""
    delay = RETRY_S
    for i in range(ATTEMPTS):
        try:
            return fn()
        except (urllib.error.URLError, OSError, ValueError) as e:  # HTTPError is a URLError
            if i == ATTEMPTS - 1 or not _retryable(e):
                raise
            log.say(f"{what}: {_why(e)}; retry {i + 1} in {delay:g} s")
            time.sleep(delay)
            delay *= 2


def _why(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"{type(e.reason).__name__}: {e.reason}"
    return f"{type(e).__name__}: {e}"


def get(url, dest, what, log, missing_ok=False):
    """GET a presigned link into the file dest. True if fetched, False if 404 and missing_ok."""
    def once():
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=HTTP_TIMEOUT_S) as r, \
                    open(dest, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 16)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404 and missing_ok:
                return False
            raise
    return _attempts(what, log, once)


def put(url, src, kind, what, log):
    """PUT the file src to a presigned link, with Content-Length (never chunked: S3 refuses that)
    and the Content-Type in TYPES[kind]."""
    size = os.path.getsize(src)

    def once():
        with open(src, "rb") as f:
            req = urllib.request.Request(url, data=f, method="PUT", headers={
                "Content-Length": str(size), "Content-Type": TYPES[kind]})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
                r.read()
    _attempts(what, log, once)
    return size


def put_bytes(url, body, kind, what, log):
    fd, path = tempfile.mkstemp(prefix="sb-remote-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        return put(url, path, kind, what, log)
    finally:
        os.unlink(path)


# ------------------------------------------------------------------ tar

def _check_member(m):
    p = PurePosixPath(m.name)
    if m.name.startswith("/") or p.is_absolute() or ".." in p.parts:
        raise Unsafe(f"{m.name!r}: outside the directory")
    if not (m.isfile() or m.isdir() or m.issym() or m.islnk()):
        raise Unsafe(f"{m.name!r}: not a file, directory or link")
    if m.issym() or m.islnk():
        target = PurePosixPath(m.linkname)
        if m.linkname.startswith("/") or target.is_absolute():
            raise Unsafe(f"{m.name!r}: links to an absolute path")
        # A symlink resolves from its own directory, a hard link from the archive's root.
        base = p.parent if m.issym() else PurePosixPath()
        depth = len(base.parts)
        for part in target.parts:
            depth += -1 if part == ".." else (0 if part == "." else 1)
            if depth < 0:
                raise Unsafe(f"{m.name!r}: links outside the directory")


def unpack(path, dest):
    """Extract a tar (or tar.gz) into dest, refusing the whole archive if any member is unsafe:
    an absolute name, a `..`, a device or fifo, a link that leaves dest. Then tarfile's own data
    filter (Python 3.12+) as a second check."""
    try:
        with tarfile.open(path, "r:*") as tf:
            members = tf.getmembers()
            for m in members:
                _check_member(m)
            if hasattr(tarfile, "data_filter"):
                tf.extractall(dest, members, filter="data")
            else:                                               # pragma: no cover - Python < 3.12
                tf.extractall(dest, members)
    except tarfile.TarError as e:
        raise Unsafe(f"{type(e).__name__}: {e}")
    return len(members)


def tree_size(root):
    """Bytes in the regular files under root (what the board's `du` cap counts, near enough)."""
    total = 0
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            if not os.path.islink(p):
                total += os.path.getsize(p)
    return total


def pack(root, path, log, gz=False):
    """Tar root's contents, relative names, sorted. Only directories and regular files go in: a
    symlink or special file is left out (and said in the log)."""
    with tarfile.open(path, "w:gz" if gz else "w", format=tarfile.PAX_FORMAT) as tf:
        for d, dirs, files in os.walk(root):
            dirs.sort()
            for name in sorted(dirs) + sorted(files):
                full = os.path.join(d, name)
                rel = os.path.relpath(full, root)
                if os.path.islink(full) or not (os.path.isdir(full) or os.path.isfile(full)):
                    log.say(f"left out of {os.path.basename(path)}: {rel} (not a file or directory)")
                    continue
                tf.add(full, arcname=rel, recursive=False)


# ------------------------------------------------------------------ the run

def _data_cap(env):
    raw = env.get("SLOWAPP_REMOTE_DATA_MAX_MB")
    if raw is None:
        try:
            with open(env.get("SLOWAPP_MANIFEST", "/app/slowapp.toml"), "rb") as f:
                raw = tomllib.load(f).get("app", {}).get("data", {}).get("max_mb")
        except (OSError, tomllib.TOMLDecodeError):
            raw = None
    try:
        return None if raw is None else float(raw) * 1024 * 1024
    except ValueError:
        return None


def _child_timeout(env):
    raw = env.get("SLOWAPP_REMOTE_TIMEOUT_S")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def run_child(cmd, env, log, timeout):
    """The job as a child: stdout and stderr together, into the log as they come. Returns its exit
    code (128 + signal if killed; 137 if it ran past timeout)."""
    p = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)

    def pump():
        while chunk := os.read(p.stdout.fileno(), 1 << 16):
            log.write(chunk)
    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        p.wait(timeout)
    except subprocess.TimeoutExpired:
        log.say(f"job ran past SLOWAPP_REMOTE_TIMEOUT_S={timeout:g}: killed")
        p.kill()
        p.wait()
        t.join(5)
        return 137
    t.join(5)
    return p.returncode if p.returncode >= 0 else 128 - p.returncode


def run(argv, entry=None, env=None, log=None):
    """`job <name>` remotely. Returns the exit code the machine should exit with."""
    env = dict(os.environ if env is None else env)
    log = log or Log()
    if len(argv) != 2 or argv[0] != "job":
        log.say("usage: slowapp-remote job <name>")
        return EXIT_CONTRACT
    name = argv[1]
    if entry is None and env.get("SLOWAPP_ENTRYPOINT"):
        try:
            entry = json.loads(env["SLOWAPP_ENTRYPOINT"])
        except ValueError:
            entry = None
    links = {k: env.get(f"SLOWAPP_REMOTE_{k.upper()}") for k in ("in", "out", "log", "data_get", "data_put")}

    work = Path(tempfile.mkdtemp(prefix="slowapp-remote-", dir=env.get("SLOWAPP_REMOTE_ROOT")))
    dirs = {k: work / k for k in ("in", "out", "data", "cache")}
    for d in dirs.values():
        d.mkdir()
    report = {"job": name, "run_id": env.get("SLOWAPP_RUN_ID"), "job_exit": None, "exit_code": None,
              "duration_ms": 0, "started_at": None, "ended_at": None, "error": None,
              "data": {"status": "none"}, "uploads_failed": []}
    code = None
    data_loaded = False             # never put /data back unless the board's old one arrived (or was absent)

    # 1. inputs
    try:
        if not entry:
            raise LookupError("no job command: keep the image's ENTRYPOINT or set SLOWAPP_ENTRYPOINT")
        if not links["in"] or not links["out"]:
            raise LookupError("SLOWAPP_REMOTE_IN and SLOWAPP_REMOTE_OUT are required")
        get(links["in"], work / "in.tar", "in.tar", log)
        n = unpack(work / "in.tar", dirs["in"])
        log.say(f"in.tar: {n} entries")
        if links["data_get"]:
            if get(links["data_get"], work / "data.tar.gz", "data", log, missing_ok=True):
                n = unpack(work / "data.tar.gz", dirs["data"])
                log.say(f"data: {n} entries")
                report["data"]["loaded"] = True
            else:
                log.say("data: none saved yet, starting empty")
                report["data"]["loaded"] = False
        data_loaded = True
    except LookupError as e:
        code, report["error"] = EXIT_CONTRACT, str(e)
        log.say(f"contract: {e}")
    except Unsafe as e:
        code, report["error"] = EXIT_TRANSIENT, f"refused an input archive: {e}"
        log.say(report["error"])
    except (urllib.error.URLError, OSError, ValueError) as e:
        code, report["error"] = EXIT_TRANSIENT, f"input fetch failed: {_why(e)}"
        log.say(report["error"])

    # 2. the job
    if code is None:
        child_env = {k: v for k, v in env.items() if not k.startswith("SLOWAPP_REMOTE_")}
        child_env.update(SLOWAPP_IN=str(dirs["in"]), SLOWAPP_OUT=str(dirs["out"]),
                         SLOWAPP_STATE=str(dirs["data"]), SLOWAPP_CACHE=str(dirs["cache"]))
        started, t0 = _now(), time.monotonic()
        report["started_at"] = _iso(started)
        log.say(f"job {name}: {' '.join(entry)} job {name}")
        try:
            code = run_child(list(entry) + ["job", name], child_env, log, _child_timeout(env))
        except OSError as e:
            code = EXIT_CONTRACT
            report["error"] = f"couldn't start the job: {e}"
            log.say(report["error"])
        report["job_exit"] = code
        report["duration_ms"] = int((time.monotonic() - t0) * 1000)
        report["ended_at"] = _iso(_now())
        log.say(f"job {name}: exit {code} in {report['duration_ms']} ms")
    final = code

    # 3. /data back, within the cap. Not when the inputs failed: the old data never arrived.
    if links["data_put"] and data_loaded and report["job_exit"] is not None:
        cap = _data_cap(env)
        size = tree_size(dirs["data"])
        report["data"].update(bytes=size)
        if cap is not None:
            report["data"]["max_mb"] = cap / (1024 * 1024)
        if cap is not None and size > cap:
            report["data"]["status"] = "over_cap"
            log.say(f"data: {size} bytes is over data.max_mb ({cap / 1048576:g} MB): not saved, the old data stays")
        else:
            try:
                pack(dirs["data"], work / "data.tar.gz", log, gz=True)
                put(links["data_put"], work / "data.tar.gz", "data", "data upload", log)
                report["data"]["status"] = "saved"
                log.say(f"data: saved ({size} bytes)")
            except (urllib.error.URLError, OSError, ValueError, tarfile.TarError) as e:
                report["data"]["status"] = "failed"
                report["uploads_failed"].append("data")
                log.say(f"data upload failed: {_why(e)}")
                final = EXIT_TRANSIENT

    # 4. /out with .remote.json
    report["exit_code"] = final
    if links["out"]:
        try:
            (dirs["out"] / ".remote.json").write_text(json.dumps(report, indent=1))
            pack(dirs["out"], work / "out.tar", log)
            size = put(links["out"], work / "out.tar", "out", "out.tar upload", log)
            log.say(f"out.tar: uploaded ({size} bytes)")
        except (urllib.error.URLError, OSError, ValueError, tarfile.TarError) as e:
            log.say(f"out.tar upload failed: {_why(e)}")
            report["uploads_failed"].append("out")
            if report["job_exit"] is not None:
                final = EXIT_TRANSIENT
    if report["uploads_failed"] and report["job_exit"] is not None:
        log.say(f"exit {final}: the job exited {report['job_exit']} but uploads failed: "
                f"{', '.join(report['uploads_failed'])}")
    else:
        log.say(f"exit {final}")

    # 5. the log tail last, so it says how the uploads went. A failed log upload only shows here,
    # in the machine's own log: out.tar already says how the run went.
    if links["log"]:
        try:
            put_bytes(links["log"], log.tail(), "log", "log upload", log)
        except (urllib.error.URLError, OSError, ValueError) as e:
            log.say(f"log upload failed: {_why(e)}")
    shutil.rmtree(work, ignore_errors=True)
    return final


def main(argv=None, entry=None):
    sys.exit(run(sys.argv[1:] if argv is None else argv, entry=entry))


if __name__ == "__main__":
    main()
