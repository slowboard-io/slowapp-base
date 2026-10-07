"""The lazy UI: HTTP/1.1 on /run/sb/ui.sock (docs/SLOWBOARD.md §8.5, M10).

  GET  /_sb/health           200 {"ok": true}
  POST /_sb/jobs/<name>      runs the job in a child; 200 {"exit": n, "message": "..."} when done.
                             Body (optional JSON), as slowbhub sends it:
                               {"run_id", "out": "/out/<run_id>", "env": {"SLOWAPP_FEEDS": ..., "TZ": ...},
                                "timeout_s"}
                             `env` carries the run's environment (§8.2); only the per-run keys in
                             RUN_ENV are applied, so a request can't move /data or the kit's paths.
                             Top-level "feeds" (a list of surfaces), "tz", "for", "deadline", "now"
                             and "reason" are accepted too and win over env.
                             Output goes to `out`, which must sit under /out (default /out/<run_id>).
  POST /_sb/events           runs the `event` job with the body (JSONL or a JSON list) as its events
  anything else              the app's own routes, registered with @route; all URLs relative

The hub blocks /_sb/* from outside and strips cookies both ways, so routes see X-Forwarded-Prefix
and X-SB-User only.
"""
import json
import os
import re
import socketserver
import sys
from http.server import BaseHTTPRequestHandler

from . import uilog
from .jobs import JOBS, run_in_child

ROUTES = []                    # (method, compiled regex, fn)
SOCK = os.environ.get("SLOWAPP_UI_SOCK", "/run/sb/ui.sock")
MAX_BODY = 4 << 20
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# The per-run part of §8.2 a warm job may set; everything else stays as the UI container started.
RUN_ENV = {"SLOWAPP_REASON", "SLOWAPP_NOW", "SLOWAPP_FOR", "SLOWAPP_DEADLINE", "SLOWAPP_FEEDS", "SLOWAPP_MODE",
           "SLOWAPP_RUN_ID", "TZ"}


def route(method, pattern):
    """Register an app route. pattern is a regex matched against the whole path (no query).
    fn(request, *groups) -> (status, headers dict, body bytes|str)."""
    rx = re.compile(pattern + r"\Z")

    def deco(fn):
        ROUTES.append((method.upper(), rx, fn))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "slowapp_kit"

    def log_message(self, fmt, *args):
        sys.stderr.write("ui: " + (fmt % args) + "\n")

    def address_string(self):
        return "ui.sock"

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("body too large")
        return self.rfile.read(n) if n else b""

    def reply(self, status, obj=None, headers=None, body=None):
        data = body if body is not None else json.dumps(obj).encode()
        if isinstance(data, str):
            data = data.encode()
        self.send_response(status)
        hdrs = {"Content-Type": "application/json"} if body is None else {}
        hdrs.update(headers or {})
        for k, v in hdrs.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self, method):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/_sb/health" and method == "GET":
                return self.reply(200, {"ok": True, "jobs": sorted(JOBS)})
            if path.startswith("/_sb/jobs/") and method == "POST":
                return self.run_job(path[len("/_sb/jobs/"):], self.body())
            if path == "/_sb/events" and method == "POST":
                return self.run_job("event", b"{}", events=self.body())
            if path.startswith("/_sb/"):
                return self.reply(404, {"error": "unknown /_sb endpoint"})
            for m, rx, fn in ROUTES:
                g = rx.match(path)
                if g and m == method:
                    status, headers, body = fn(self, *g.groups())
                    return self.reply(status, headers=headers, body=body)
            return self.reply(404, {"error": "not found"})
        except ValueError as e:
            return self.reply(400, {"error": str(e)})

    def run_job(self, name, raw, events=None):
        if name not in JOBS:
            return self.reply(404, {"exit": 64, "message": f"no job {name!r}"})
        req = json.loads(raw or b"{}")
        if not isinstance(req, dict):
            raise ValueError("job request must be a JSON object")
        run_id = req.get("run_id") or f"r_ui_{os.getpid()}"
        if not RUN_ID_RE.match(run_id):
            raise ValueError(f"bad run_id {run_id!r}")
        env = {"SLOWAPP_REASON": "manual"}
        sent = req.get("env") or {}
        if not isinstance(sent, dict):
            raise ValueError("env must be an object")
        ignored = sorted(k for k in sent if k not in RUN_ENV)
        if ignored:
            sys.stderr.write(f"ui: job {name}: ignoring env {', '.join(ignored)}\n")
        env.update({k: str(v) for k, v in sent.items() if k in RUN_ENV})
        for k, var in (("for", "SLOWAPP_FOR"), ("deadline", "SLOWAPP_DEADLINE"), ("now", "SLOWAPP_NOW"),
                       ("reason", "SLOWAPP_REASON"), ("tz", "TZ")):
            if req.get(k):
                env[var] = str(req[k])
        if req.get("feeds") is not None:          # surfaces as a list (or the SLOWAPP_FEEDS string)
            feeds = req["feeds"]
            env["SLOWAPP_FEEDS"] = feeds if isinstance(feeds, str) else json.dumps(feeds)
        env.update(SLOWAPP_JOB=name, SLOWAPP_RUN_ID=run_id)
        base = os.path.normpath(os.environ.get("SLOWAPP_OUT", "/out"))
        out = os.path.normpath(os.path.join(base, req["out"] if req.get("out") else run_id))
        if os.path.commonpath([base, out]) != base or out == base:
            raise ValueError(f"out {req.get('out')!r} must be a directory under {base}")
        code, msg = run_in_child(name, env, out=out, events_body=events, timeout=req.get("timeout_s"))
        return self.reply(200, {"exit": code, "message": msg})

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def make_server(path=None):
    path = path or SOCK
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = Server(path, Handler)
    os.chmod(path, 0o660)
    return srv


def serve(path=None):
    uilog.install()
    srv = make_server(path)
    sys.stderr.write(f"ui: listening on {path or SOCK}\n")
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
