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

Contract 6 adds two things. A job that should have no network (a render job, or any job of an
app whose network is none) runs in an empty network namespace, after the wrapper has fetched its
inputs. And with SLOWAPP_REMOTE_KEY_FILE, every object is sealed with a per-run key (seal.py): the
wrapper reads the key, deletes the file before the job starts, opens in.tar and the saved data,
and seals out.tar, data.tar.gz and the log.

Standard library only: the base images gain no dependency.
"""
import base64
import fcntl
import http.client
import json
import math
import os
import shutil
import signal
import socket
import ssl
import struct
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

from . import manifest as mf
from . import seal
from .errors import EXIT_CONTRACT, EXIT_TRANSIENT, ContractError

LOG_TAIL = 64 * 1024
HTTP_TIMEOUT_S = 60
ATTEMPTS = 3
# Seconds before the first retry, doubling after; the tests set it to 0.
RETRY_S = float(os.environ.get("SLOWAPP_REMOTE_RETRY_S", "2"))
# Seconds between SIGTERM and SIGKILL for the job child when the machine is stopped.
STOP_GRACE_S = float(os.environ.get("SLOWAPP_REMOTE_STOP_GRACE_S", "3"))
TYPES = {"out": "application/x-tar", "data": "application/gzip", "log": "text/plain; charset=utf-8",
         "sealed": "application/octet-stream"}


class Unsafe(Exception):
    """A tar member that would land outside its directory, or isn't a plain file, dir or link."""


class Log:
    """The run's combined output: streamed to our stdout (the machine's log) and its last 64 KiB
    kept for the log upload."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stdout.buffer
        self.buf = bytearray()
        self.lock = threading.Lock()
        # A sealed run keeps the job's own output out of the machine's log (only the sealed log
        # upload has it); the wrapper's lines still go to both.
        self.echo_job = True

    def write(self, b, echo=True):
        with self.lock:
            if echo:
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

# What a request can raise: HTTPError is a URLError; IncompleteRead, BadStatusLine and the rest of
# http.client's are HTTPExceptions; refused, reset, DNS and timeouts are OSErrors.
NET_ERRORS = (urllib.error.URLError, OSError, ValueError, http.client.HTTPException)
# Errors that the same request would hit again: a local file we can't open, a link urllib can't
# use, a certificate that doesn't verify (an SSLCertVerificationError is also a ValueError).
PERMANENT = (FileNotFoundError, PermissionError, IsADirectoryError, NotADirectoryError,
             ssl.SSLCertVerificationError, ValueError)


def _retryable(e):
    if isinstance(e, urllib.error.HTTPError):
        return e.code >= 500 or e.code in (408, 429)
    if isinstance(e, urllib.error.URLError):
        if not isinstance(e.reason, BaseException):     # "unknown url type: …"
            return False
        e = e.reason
    return not isinstance(e, PERMANENT)


def _attempts(what, log, fn):
    """fn() with retries on network errors and 5xx. Returns fn's value; raises the last error."""
    delay = RETRY_S
    for i in range(ATTEMPTS):
        try:
            return fn()
        except NET_ERRORS as e:
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
                if r.length:                    # read(n) takes a body cut short as its end
                    raise http.client.IncompleteRead(b"", r.length)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404 and missing_ok:
                return False
            raise
    return _attempts(what, log, once)


def _put(url, body, size, kind):
    """One PUT, with Content-Length (never chunked: S3 refuses that) and the Content-Type in
    TYPES[kind]. body is bytes or an open file."""
    req = urllib.request.Request(url, data=body, method="PUT", headers={
        "Content-Length": str(size), "Content-Type": TYPES[kind]})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
        r.read()


def put(url, src, kind, what, log):
    """PUT the file src to a presigned link."""
    size = os.path.getsize(src)

    def once():
        with open(src, "rb") as f:
            _put(url, f, size, kind)
    _attempts(what, log, once)
    return size


def put_bytes(url, body, kind, what, log):
    _attempts(what, log, lambda: _put(url, body, len(body), kind))
    return len(body)


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
    symlink or special file is left out (and said in the log), and a file with other hard links
    goes in as a whole regular file, never as a link member."""
    with tarfile.open(path, "w:gz" if gz else "w", format=tarfile.PAX_FORMAT) as tf:
        for d, dirs, files in os.walk(root):
            dirs.sort()
            for name in dirs + sorted(files):
                full = os.path.join(d, name)
                rel = os.path.relpath(full, root)
                if os.path.islink(full) or not (os.path.isdir(full) or os.path.isfile(full)):
                    log.say(f"left out of {os.path.basename(path)}: {rel} (not a file or directory)")
                    continue
                ti = tf.gettarinfo(full, arcname=rel)
                if ti.isdir():
                    tf.addfile(ti)
                    continue
                # gettarinfo makes a second name for an inode a hard link (size 0): undo that.
                ti.type, ti.linkname, ti.size = tarfile.REGTYPE, "", os.path.getsize(full)
                with open(full, "rb") as f:
                    tf.addfile(ti, f)


# ------------------------------------------------------------------ sealing (contract 6)

def read_keys(env):
    """SLOWAPP_REMOTE_KEY_FILE: the run's key, read and then deleted, so the job can't read it.
    The file is the key in base64 (32 bytes), or JSON {"key": base64, "data_key": base64}, where
    data_key (default: key) seals the saved /data both ways, so the hub can keep one per board and
    never re-seal it. Returns {"key", "data"} or None when the variable is unset. ContractError if
    the file can't be read or deleted, isn't a key, or there's nothing to seal with."""
    path = env.get("SLOWAPP_REMOTE_KEY_FILE")
    if not path:
        return None
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        raise ContractError(f"SLOWAPP_REMOTE_KEY_FILE: {e}")
    try:
        os.unlink(path)
    except OSError as e:
        raise ContractError(f"SLOWAPP_REMOTE_KEY_FILE: can't delete it before the job runs ({e})")

    def key(v, what):
        try:
            k = base64.b64decode(v, validate=True)
        except (ValueError, TypeError):
            k = b""
        if len(k) != seal.KEY:
            raise ContractError(f"SLOWAPP_REMOTE_KEY_FILE: {what} isn't {seal.KEY} bytes in base64")
        return k
    text = raw.strip()
    if text.startswith(b"{"):
        try:
            obj = json.loads(text)
        except ValueError:
            obj = None
        if not isinstance(obj, dict) or "key" not in obj:
            raise ContractError('SLOWAPP_REMOTE_KEY_FILE: JSON must be {"key": …, "data_key": …}')
        keys = {"key": key(obj["key"], "key")}
        keys["data"] = key(obj["data_key"], "data_key") if obj.get("data_key") else keys["key"]
    else:
        keys = {"key": key(text, "the key")}
        keys["data"] = keys["key"]
    try:
        seal.aead()
    except seal.SealError as e:
        raise ContractError(str(e))
    return keys


# ------------------------------------------------------------------ no network (contract 6)

def _load_manifest(env):
    try:
        with open(env.get("SLOWAPP_MANIFEST", "/app/slowapp.toml"), "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def network_wanted(env, name, manifest):
    """"none" when the job must run without the network: a contract 6 render job, any job of an
    app whose network is none, or SLOWAPP_REMOTE_NETWORK=none (the hub's word; "egress" there
    never loosens the manifest). "egress" otherwise, and when there's no manifest to go by."""
    raw = env.get("SLOWAPP_REMOTE_NETWORK") or ""
    if raw not in ("", "none", "egress"):
        raise ContractError(f"SLOWAPP_REMOTE_NETWORK={raw!r}: none or egress")
    if raw == "none":
        return "none"
    if manifest and mf.job_spec(manifest, name)["network"] == "none":
        return "none"
    return "egress"


SIOCGIFFLAGS, SIOCSIFFLAGS, IFF_UP = 0x8913, 0x8914, 0x1


def _loopback_up():
    """Bring lo up in a new network namespace (as Podman's --network none has it): the job may
    talk to itself, and nothing else."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ifr = fcntl.ioctl(s, SIOCGIFFLAGS, struct.pack("16sH22s", b"lo", 0, b""))
        flags = struct.unpack("16sH", ifr[:18])[1]
        fcntl.ioctl(s, SIOCSIFFLAGS, struct.pack("16sH22s", b"lo", flags | IFF_UP, b""))
    finally:
        s.close()


def _enter_empty_netns():
    """preexec_fn of the job child: a network namespace of its own, with only lo."""
    os.unshare(os.CLONE_NEWNET)
    try:
        _loopback_up()
    except OSError:
        pass


def netns_unavailable():
    """None if this process can give a child an empty network namespace (root with
    CAP_SYS_ADMIN, as on a Fly Machine), else why not. Tried in a forked child, which exits at once."""
    if not hasattr(os, "unshare") or not hasattr(os, "CLONE_NEWNET"):
        return "this system has no network namespaces (os.unshare needs Linux and Python 3.12)"
    pid = os.fork()
    if pid == 0:                                    # pragma: no cover - the child
        try:
            os.unshare(os.CLONE_NEWNET)
            os._exit(0)
        except OSError as e:
            os._exit(e.errno if 0 < e.errno < 256 else 255)
        except BaseException:
            os._exit(255)
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    if code == 0:
        return None
    return f"unshare(CLONE_NEWNET): {os.strerror(code) if 0 < code < 255 else 'failed'}"


# ------------------------------------------------------------------ the run

def _data_cap(env):
    raw = env.get("SLOWAPP_REMOTE_DATA_MAX_MB")
    if raw is None:
        raw = _load_manifest(env).get("app", {}).get("data", {}).get("max_mb")
    try:
        return None if raw is None else float(raw) * 1024 * 1024
    except ValueError:
        return None


def _child_timeout(env):
    """SLOWAPP_REMOTE_TIMEOUT_S as seconds, or None for no limit (unset, empty, 0 or less)."""
    raw = (env.get("SLOWAPP_REMOTE_TIMEOUT_S") or "").strip()
    if not raw:
        return None
    try:
        t = float(raw)
    except ValueError:
        t = math.nan
    if math.isnan(t):
        raise ContractError(f"SLOWAPP_REMOTE_TIMEOUT_S={raw!r} isn't a number of seconds")
    return None if t <= 0 or math.isinf(t) else t


def parse_entrypoint(raw):
    """SLOWAPP_ENTRYPOINT: a non-empty JSON list of strings, the app's command. ContractError if not
    (also for jobs.entrypoint)."""
    try:
        cmd = json.loads(raw)
    except ValueError:
        cmd = None
    if not (isinstance(cmd, list) and cmd and all(isinstance(a, str) and a for a in cmd)):
        raise ContractError(f"SLOWAPP_ENTRYPOINT must be a non-empty JSON list of strings, not {raw!r}")
    return cmd


class Stop:
    """SIGTERM or SIGINT (the machine being stopped): noted, the job child gets SIGTERM and then
    SIGKILL after STOP_GRACE_S, and the run goes on to its uploads. Traps only on the main thread."""

    def __init__(self):
        self.signum, self.child, self.old = None, None, {}

    def __enter__(self):
        for s in (signal.SIGTERM, signal.SIGINT):
            try:
                self.old[s] = signal.signal(s, self.handle)
            except ValueError:                      # not the main thread
                pass
        return self

    def __exit__(self, *exc):
        for s, h in self.old.items():
            signal.signal(s, h)

    def handle(self, signum, frame):
        # No logging here: the handler can run while the main thread holds the log's lock.
        if self.signum is None:
            self.signum = signum
        if self.child is not None:
            self.end(self.child)

    def end(self, p):
        p.terminate()                               # a no-op once it has been reaped
        t = threading.Timer(STOP_GRACE_S, p.kill)
        t.daemon = True
        t.start()

    def name(self):
        return signal.Signals(self.signum).name


def run_child(cmd, env, log, timeout, stop=None, isolate=False):
    """The job as a child: stdout and stderr together, into the log as they come. Returns its exit
    code (128 + signal if killed; 137 if it ran past timeout). stop: a Stop to hand the child to.
    isolate: run it in an empty network namespace (OSError if that fails: it doesn't run)."""
    # Looked up first: under qemu-user a missing program comes back as exit 127, not an OSError.
    if shutil.which(cmd[0], path=env.get("PATH", os.defpath)) is None:
        raise FileNotFoundError(f"no such program: {cmd[0]}")
    try:
        p = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, preexec_fn=_enter_empty_netns if isolate else None)
    except subprocess.SubprocessError as e:
        raise OSError(f"couldn't give the job an empty network namespace: {e}")
    if stop is not None:
        stop.child = p
        if stop.signum is not None:                 # stopped while it was starting
            stop.end(p)

    def pump():
        while chunk := os.read(p.stdout.fileno(), 1 << 16):
            log.write(chunk, echo=log.echo_job)
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


def fetch(url, dest, what, log, key=None, label=None, missing_ok=False):
    """get(), and with a key, open the sealed object into dest. Unsafe if it doesn't open."""
    if key is None:
        return get(url, dest, what, log, missing_ok)
    sealed = Path(f"{dest}.sealed")
    try:
        if not get(url, sealed, what, log, missing_ok):
            return False
        try:
            seal.open_file(key, label, sealed, dest)
        except seal.SealError as e:
            raise Unsafe(f"{what} doesn't open with the run's key ({e})")
    finally:
        sealed.unlink(missing_ok=True)
    return True


def upload(url, src, kind, what, log, key=None, label=None):
    """put(), and with a key, the sealed file instead (application/octet-stream)."""
    if key is None:
        return put(url, src, kind, what, log)
    sealed = Path(f"{src}.sealed")
    try:
        seal.seal_file(key, label, src, sealed)
        return put(url, sealed, "sealed", what, log)
    finally:
        sealed.unlink(missing_ok=True)


def run(argv, entry=None, env=None, log=None):
    """`job <name>` remotely. Returns the exit code the machine should exit with. entry is the
    app's command; None reads SLOWAPP_ENTRYPOINT."""
    with Stop() as stop:
        return _run(argv, entry, dict(os.environ if env is None else env), log or Log(), stop)


def _run(argv, entry, env, log, stop):
    if len(argv) != 2 or argv[0] != "job":
        log.say("usage: slowapp-remote job <name>")
        return EXIT_CONTRACT
    name = argv[1]
    links = {k: env.get(f"SLOWAPP_REMOTE_{k.upper()}") for k in ("in", "out", "log", "data_get", "data_put")}

    work = Path(tempfile.mkdtemp(prefix="slowapp-remote-", dir=env.get("SLOWAPP_REMOTE_ROOT")))
    dirs = {k: work / k for k in ("in", "out", "data", "cache")}
    for d in dirs.values():
        d.mkdir()
    report = {"job": name, "run_id": env.get("SLOWAPP_RUN_ID"), "job_exit": None, "exit_code": None,
              "duration_ms": 0, "started_at": None, "ended_at": None, "error": None,
              "data": {"status": "none"}, "uploads_failed": [], "sealed": False,
              "network": {"wanted": "egress", "isolated": False, "error": None}}
    code = None
    # /data goes back only if the board's saved one arrived, or the hub said there's none yet:
    # never an empty /data over saved data the wrapper didn't see.
    data_known = False
    keys = {}

    # 1. inputs
    try:
        # First of all: the key file is gone before anything else can run.
        try:
            keys = read_keys(env) or {}
        finally:
            if env.get("SLOWAPP_REMOTE_KEY_FILE"):          # also when it wasn't a key
                try:
                    Path(env["SLOWAPP_REMOTE_KEY_FILE"]).unlink(missing_ok=True)
                except OSError:
                    pass
        if keys:
            report["sealed"] = True
            log.echo_job = False
            log.say(f"sealed run: objects open and seal with the run's key ({seal.aead().name}); "
                    "the job's output goes only to the sealed log")
        report["network"]["wanted"] = network_wanted(env, name, _load_manifest(env))
        if entry is None and env.get("SLOWAPP_ENTRYPOINT"):
            entry = parse_entrypoint(env["SLOWAPP_ENTRYPOINT"])
        if not entry:
            raise ContractError("no job command: keep the image's ENTRYPOINT or set SLOWAPP_ENTRYPOINT")
        timeout = _child_timeout(env)
        if not links["in"] or not links["out"]:
            raise ContractError("SLOWAPP_REMOTE_IN and SLOWAPP_REMOTE_OUT are required")
        fetch(links["in"], work / "in.tar", "in.tar", log, keys.get("key"), "in")
        n = unpack(work / "in.tar", dirs["in"])
        log.say(f"in.tar: {n} entries")
        if links["data_get"]:
            if fetch(links["data_get"], work / "data.tar.gz", "data", log, keys.get("data"), "data", missing_ok=True):
                n = unpack(work / "data.tar.gz", dirs["data"])
                log.say(f"data: {n} entries")
                report["data"]["loaded"] = True
            else:
                log.say("data: none saved yet, starting empty")
                report["data"]["loaded"] = False
            data_known = True
        elif env.get("SLOWAPP_REMOTE_DATA_NEW") == "1":
            log.say("data: none saved yet (SLOWAPP_REMOTE_DATA_NEW), starting empty")
            report["data"]["loaded"] = False
            data_known = True
        elif links["data_put"]:
            log.say("data: SLOWAPP_REMOTE_DATA_PUT without DATA_GET or DATA_NEW=1: "
                    "starting empty, and /data won't be saved")
    except ContractError as e:
        code, report["error"] = EXIT_CONTRACT, str(e)
        log.say(f"contract: {e}")
    except Unsafe as e:
        code, report["error"] = EXIT_TRANSIENT, f"refused an input archive: {e}"
        log.say(report["error"])
    except NET_ERRORS as e:
        code, report["error"] = EXIT_TRANSIENT, f"input fetch failed: {_why(e)}"
        log.say(report["error"])
    if code is None and stop.signum is not None:
        code, report["error"] = 128 + stop.signum, f"stopped by {stop.name()} before the job ran"
        log.say(report["error"])

    # 2. the job, without the network if it should have none
    isolate = False
    if code is None and report["network"]["wanted"] == "none":
        why = netns_unavailable()
        if why is None:
            isolate = report["network"]["isolated"] = True
            log.say(f"job {name}: no network (an empty network namespace)")
        else:
            report["network"]["error"] = why
            log.say(f"WARNING: job {name} should run without the network, but {why}. "
                    "It runs WITH the network (.remote.json network.isolated is false)")
    if code is None:
        child_env = {k: v for k, v in env.items() if not k.startswith("SLOWAPP_REMOTE_")}
        child_env.update(SLOWAPP_IN=str(dirs["in"]), SLOWAPP_OUT=str(dirs["out"]),
                         SLOWAPP_STATE=str(dirs["data"]), SLOWAPP_CACHE=str(dirs["cache"]))
        started, t0 = _now(), time.monotonic()
        report["started_at"] = _iso(started)
        log.say(f"job {name}: {' '.join(entry)} job {name}")
        try:
            code = report["job_exit"] = run_child(list(entry) + ["job", name], child_env, log, timeout, stop, isolate)
        except OSError as e:                        # it never ran: job_exit stays null
            code = EXIT_CONTRACT
            report["error"] = f"couldn't start the job: {e}"
            log.say(report["error"])
        report["duration_ms"] = int((time.monotonic() - t0) * 1000)
        report["ended_at"] = _iso(_now())
        if report["job_exit"] is not None:
            log.say(f"job {name}: exit {code} in {report['duration_ms']} ms")
        if stop.signum is not None:
            report["error"] = report["error"] or f"stopped by {stop.name()}"
            log.say(f"stopped by {stop.name()}: uploading what the job left")
    final = code

    # 3. /data back, within the cap. Not when the job didn't run (the inputs failed: the old data
    # never arrived), nor when the saved data is unknown.
    if links["data_put"] and data_known and report["job_exit"] is not None:
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
                upload(links["data_put"], work / "data.tar.gz", "data", "data upload", log, keys.get("data"), "data")
                report["data"]["status"] = "saved"
                log.say(f"data: saved ({size} bytes)")
            except (*NET_ERRORS, tarfile.TarError, seal.SealError) as e:
                report["data"]["status"] = "failed"
                report["uploads_failed"].append("data")
                log.say(f"data upload failed: {_why(e)}")
                final = EXIT_TRANSIENT

    # 4. /out with .remote.json. A stop, until now, makes the exit 128 + its signal.
    if stop.signum is not None:
        final = 128 + stop.signum
    report["exit_code"] = final
    if links["out"]:
        try:
            (dirs["out"] / ".remote.json").write_text(json.dumps(report, indent=1))
            pack(dirs["out"], work / "out.tar", log)
            size = upload(links["out"], work / "out.tar", "out", "out.tar upload", log, keys.get("key"), "out")
            log.say(f"out.tar: uploaded ({size} bytes)")
        except (*NET_ERRORS, tarfile.TarError, seal.SealError) as e:
            log.say(f"out.tar upload failed: {_why(e)}")
            report["uploads_failed"].append("out")
            if report["job_exit"] is not None and stop.signum is None:
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
            if keys:
                put_bytes(links["log"], seal.seal_bytes(keys["key"], "log", log.tail()), "sealed", "log upload", log)
            else:
                put_bytes(links["log"], log.tail(), "log", "log upload", log)
        except (*NET_ERRORS, seal.SealError) as e:
            log.say(f"log upload failed: {_why(e)}")
    shutil.rmtree(work, ignore_errors=True)
    return final


def main(argv=None, entry=None):
    sys.exit(run(sys.argv[1:] if argv is None else argv, entry=entry))


if __name__ == "__main__":
    main()
