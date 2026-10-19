"""slowapp-remote: a job run from presigned links (the cloud hub's Fly Machines; MANIFEST.md,
"Remote runs"). A local HTTP server stands in for the presigned GET and PUT links; sample_app.py's
`remote` job is the app. S3Links runs the same against a real S3 API (versitygw in CI) when
SLOWAPP_TEST_S3 names one, with links signed by a stdlib SigV4 presigner.

  PYTHONPATH=kit python3 -m unittest discover -s kit/tests -p 'test_remote.py'
"""
import base64
import gzip
import hashlib
import hmac
import http.client
import io
import json
import os
import signal
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from unittest import mock
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from slowapp_kit import jobs, remote, seal
from slowapp_kit.errors import ContractError

HERE = Path(__file__).resolve().parent
APP = [sys.executable, str(HERE / "sample_app.py")]
FEEDS = json.dumps([{"feed": "left", "slot": "left", "w": 452, "h": 444, "inks": "k4", "bpp": 2}])


def tar_bytes(files, gz=False, extra=()):
    """{name: bytes} (and raw TarInfo members in extra) as a tar."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz" if gz else "w") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        for ti in extra:
            tf.addfile(ti)
    return buf.getvalue()


def untar(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        return {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}


def link(name, kind):
    ti = tarfile.TarInfo(name)
    ti.type, ti.linkname = kind
    return ti


class Store(ThreadingHTTPServer):
    """Objects by path. GET: 200 or 404. PUT: stores the body. `fail` answers a path, or a
    (method, path), with an error; `garble` answers a GET with a broken response ("status": not
    HTTP at all, "short": less body than its Content-Length)."""
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.objects, self.types, self.fail, self.chunked, self.hits, self.garble = {}, {}, {}, [], {}, {}
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def url(self, path):
        return f"http://127.0.0.1:{self.server_address[1]}/{path}?X-Amz-Signature=test"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _path(self):
        s = self.server
        p = urllib.parse.urlsplit(self.path).path.lstrip("/")
        s.hits[(self.command, p)] = s.hits.get((self.command, p), 0) + 1
        return p

    def _fail(self, p):
        return self.server.fail.get((self.command, p)) or self.server.fail.get(p)

    def do_GET(self):
        p = self._path()
        if self._fail(p):
            return self.send_error(self._fail(p))
        how = self.server.garble.get(p)
        if how == "status":
            self.wfile.write(b"garbage\r\n\r\n")
            self.close_connection = True
            return
        if how == "short":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"x" * 10)
            self.close_connection = True
            return
        body = self.server.objects.get(p)
        if body is None:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        p = self._path()
        if "chunked" in self.headers.get("Transfer-Encoding", ""):
            self.server.chunked.append(p)
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self._fail(p):
            return self.send_error(self._fail(p))
        self.server.objects[p], self.server.types[p] = body, self.headers.get("Content-Type")
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


class RemoteBase(unittest.TestCase):
    """The store and the helpers; Remote, Sealed and Network hold the tests."""

    @classmethod
    def setUpClass(cls):
        cls.store = Store()

    @classmethod
    def tearDownClass(cls):
        cls.store.shutdown()

    def setUp(self):
        s = self.store
        s.objects.clear(), s.types.clear(), s.fail.clear(), s.chunked.clear(), s.hits.clear(), s.garble.clear()
        self.tmp = Path(tempfile.mkdtemp())
        self.settings({})

    def settings(self, settings, files=None):
        self.store.objects["runs/r1/in.tar"] = tar_bytes(dict(
            {"settings.json": json.dumps(settings).encode(), "./docs/notes.json": b'{"n": 1}'}, **(files or {})))

    def env(self, **kw):
        s = self.store
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLOWAPP_")}
        env.update(SLOWAPP_CONTRACT="5", SLOWAPP_APP="test", SLOWAPP_JOB="remote", SLOWAPP_RUN_ID="r1",
                   SLOWAPP_MODE="live", SLOWAPP_NOW="2026-10-18T09:00:00-07:00",
                   SLOWAPP_DEADLINE="2026-10-18T09:01:00-07:00", TZ="America/Vancouver", SLOWAPP_FEEDS=FEEDS,
                   SLOWAPP_MANIFEST=str(self.tmp / "none.toml"), SLOWAPP_JOB_LOCK=str(self.tmp / "lock"),
                   SLOWAPP_REMOTE_ROOT=str(self.tmp), SLOWAPP_REMOTE_RETRY_S="0",
                   SLOWAPP_REMOTE_IN=s.url("runs/r1/in.tar"), SLOWAPP_REMOTE_OUT=s.url("runs/r1/out.tar"),
                   SLOWAPP_REMOTE_LOG=s.url("runs/r1/log"),
                   SLOWAPP_REMOTE_DATA_GET=s.url("data/test/b1.tar.gz"),
                   SLOWAPP_REMOTE_DATA_PUT=s.url("data/test/b1.tar.gz"), SLOWAPP_REMOTE_DATA_MAX_MB="1")
        env.update({k: v for k, v in kw.items() if v is not None})
        for k in [k for k, v in kw.items() if v is None]:
            env.pop(k, None)
        return env

    def run_remote(self, job="remote", cmd=None, **kw):
        p = subprocess.run((cmd or APP + ["slowapp-remote"]) + ["job", job], env=self.env(**kw),
                           capture_output=True, timeout=60)
        self.stdout = p.stdout.decode()
        return p.returncode

    def out(self):
        return untar(self.store.objects["runs/r1/out.tar"])

    def report(self):
        return json.loads(self.out()[".remote.json"])

    def log(self):
        return self.store.objects["runs/r1/log"].decode()

    def data(self):
        return untar(self.store.objects["data/test/b1.tar.gz"])



class Remote(RemoteBase):
    # ------------------------------------------------------------------ a run end to end

    def test_inputs_in_outputs_back(self):
        self.settings({"hello": "there"})
        self.assertEqual(self.run_remote(), 0, self.stdout)
        out = self.out()
        seen = json.loads(out["seen.json"])
        self.assertEqual(seen["settings"], {"hello": "there"})
        self.assertEqual(seen["docs"], {"notes": {"n": 1}})
        self.assertEqual(seen["remote_env"], [], "the links aren't the app's")
        for k in ("in", "data", "cache"):
            self.assertTrue(seen[k].startswith(str(self.tmp)), seen[k])
        self.assertIn("feeds/left/deck.json", out)
        self.assertIn("feeds/left/cards/home.png", out)
        metrics = json.loads(out[".metrics.json"])
        self.assertEqual(metrics["exit"], 0)
        rep = self.report()
        self.assertEqual((rep["exit_code"], rep["job_exit"], rep["uploads_failed"]), (0, 0, []))
        self.assertGreater(rep["duration_ms"], 0)
        self.assertLessEqual(rep["started_at"], rep["ended_at"])
        self.assertTrue(rep["started_at"].endswith("Z"))
        self.assertEqual(rep["data"]["status"], "saved")
        self.assertFalse(rep["data"]["loaded"])
        # the log: the job's stdout and stderr, and the wrapper's lines; also on the machine's stdout
        log = self.log()
        for line in ("remote job: to stdout", "remote job: to stderr", "slowapp-remote: exit 0"):
            self.assertIn(line, log)
            self.assertIn(line, self.stdout)
        s = self.store
        self.assertEqual(s.types["runs/r1/log"], "text/plain; charset=utf-8")
        self.assertEqual(s.types["runs/r1/out.tar"], "application/x-tar")
        self.assertEqual(s.types["data/test/b1.tar.gz"], "application/gzip")
        self.assertEqual(s.chunked, [])
        self.assertTrue(gzip.decompress(s.objects["data/test/b1.tar.gz"]))
        self.assertEqual(list(self.tmp.glob("slowapp-remote-*")), [], "the wrapper cleans up after itself")

    def test_data_round_trips(self):
        self.assertEqual(self.run_remote(), 0, self.stdout)
        self.assertEqual(self.data()["count.txt"], b"1")
        self.assertNotIn("scratch", "".join(self.data()), "/cache isn't saved")
        self.assertEqual(self.run_remote(), 0, self.stdout)
        self.assertEqual(self.data()["count.txt"], b"2")
        self.assertTrue(self.report()["data"]["loaded"])
        self.assertEqual(json.loads(self.out()["seen.json"])["count"], 2)

    def test_no_data_links_no_data(self):
        self.assertEqual(self.run_remote(SLOWAPP_REMOTE_DATA_GET=None, SLOWAPP_REMOTE_DATA_PUT=None), 0)
        self.assertNotIn("data/test/b1.tar.gz", self.store.objects)
        self.assertEqual(self.report()["data"], {"status": "none"})

    def test_data_over_the_cap_keeps_the_old(self):
        self.assertEqual(self.run_remote(), 0)
        old = self.store.objects["data/test/b1.tar.gz"]
        self.settings({"big_kb": 200})
        self.assertEqual(self.run_remote(SLOWAPP_REMOTE_DATA_MAX_MB="0.1"), 0, "over the cap isn't a failure")
        self.assertEqual(self.store.objects["data/test/b1.tar.gz"], old)
        self.assertEqual(self.store.hits[("PUT", "data/test/b1.tar.gz")], 1)
        rep = self.report()
        self.assertEqual(rep["data"]["status"], "over_cap")
        self.assertGreater(rep["data"]["bytes"], 200 * 1024)
        self.assertEqual(rep["data"]["max_mb"], 0.1)
        self.assertIn("over data.max_mb", self.log())

    def test_cap_from_the_manifest(self):
        (self.tmp / "slowapp.toml").write_text('[app]\nid = "test"\ndata = { max_mb = 0.1 }\n')
        self.settings({"big_kb": 200})
        self.assertEqual(self.run_remote(SLOWAPP_REMOTE_DATA_MAX_MB=None,
                                         SLOWAPP_MANIFEST=str(self.tmp / "slowapp.toml")), 0)
        self.assertEqual(self.report()["data"]["status"], "over_cap")
        self.assertNotIn("data/test/b1.tar.gz", self.store.objects)

    def test_exit_codes_preserved(self):
        for code in (3, 5, 1):
            with self.subTest(code=code):
                self.settings({"exit": code})
                self.assertEqual(self.run_remote(), code, self.stdout)
                rep = self.report()
                self.assertEqual((rep["exit_code"], rep["job_exit"]), (code, code))
                self.assertEqual(json.loads(self.out()[".metrics.json"])["exit"], code)
                self.assertEqual(rep["data"]["status"], "saved", "/data persists whatever the exit, as on a board")
        self.assertIn("RuntimeError: bug", self.log())

    def test_job_past_its_timeout_is_killed(self):
        self.settings({"sleep": 30})
        self.assertEqual(self.run_remote(SLOWAPP_REMOTE_TIMEOUT_S="1"), 137)
        self.assertEqual(self.report()["job_exit"], 137)
        self.assertIn("killed", self.log())

    # ------------------------------------------------------------------ failures

    def test_failed_input_fetch_exits_4(self):
        self.store.fail["runs/r1/in.tar"] = 503
        self.assertEqual(self.run_remote(), 4)
        self.assertEqual(self.store.hits[("GET", "runs/r1/in.tar")], remote.ATTEMPTS, "retried")
        rep = self.report()
        self.assertEqual((rep["exit_code"], rep["job_exit"]), (4, None))
        self.assertIn("input fetch failed: HTTP 503", rep["error"])
        self.assertNotIn("seen.json", self.out())
        self.assertIn("input fetch failed", self.log())
        self.assertNotIn(("PUT", "data/test/b1.tar.gz"), self.store.hits, "never overwrite data it didn't get")

    def test_missing_input_and_bad_data_fetch_exit_4(self):
        del self.store.objects["runs/r1/in.tar"]
        self.assertEqual(self.run_remote(), 4)
        self.assertEqual(self.store.hits[("GET", "runs/r1/in.tar")], 1, "a 404 isn't retried")
        self.settings({})
        self.store.fail["data/test/b1.tar.gz"] = 403
        self.assertEqual(self.run_remote(), 4)
        self.assertIn("HTTP 403", self.report()["error"])

    def test_unreachable_store_exits_4(self):
        self.assertEqual(self.run_remote(SLOWAPP_REMOTE_IN="http://127.0.0.1:9/in.tar"), 4)
        self.assertIn("input fetch failed", self.report()["error"])

    def test_unsafe_input_refused(self):
        bad = {
            "dotdot": tar_bytes({"../evil": b"x"}),
            "absolute": tar_bytes({"/tmp/evil": b"x"}),
            "symlink out": tar_bytes({}, extra=[link("docs", (tarfile.SYMTYPE, "../../.."))]),
            "symlink absolute": tar_bytes({}, extra=[link("settings.json", (tarfile.SYMTYPE, "/etc/passwd"))]),
            "hard link out": tar_bytes({}, extra=[link("x", (tarfile.LNKTYPE, "../x"))]),
            "device": tar_bytes({}, extra=[link("null", (tarfile.CHRTYPE, ""))]),
        }
        for why, data in bad.items():
            with self.subTest(why):
                self.store.objects["runs/r1/in.tar"] = data
                self.assertEqual(self.run_remote(), 4, self.stdout)
                rep = self.report()
                self.assertIsNone(rep["job_exit"])
                self.assertIn("refused an input archive", rep["error"])
        self.assertFalse((self.tmp.parent / "evil").exists())

    def test_unsafe_data_refused(self):
        self.store.objects["data/test/b1.tar.gz"] = tar_bytes({"../evil": b"x"}, gz=True)
        self.assertEqual(self.run_remote(), 4)
        self.assertNotIn(("PUT", "data/test/b1.tar.gz"), self.store.hits)

    def test_unpack_safe_links_and_refusals(self):
        log = remote.Log(io.BytesIO())
        d = self.tmp / "x"
        d.mkdir()
        tar = self.tmp / "ok.tar"
        tar.write_bytes(tar_bytes({"a/b.txt": b"b"}, extra=[link("a/c", (tarfile.SYMTYPE, "b.txt")),
                                                             link("a/d", (tarfile.LNKTYPE, "a/b.txt"))]))
        self.assertEqual(remote.unpack(tar, d), 3)
        self.assertEqual((d / "a" / "c").read_text(), "b")
        self.assertEqual((d / "a" / "d").read_text(), "b")
        tar.write_bytes(tar_bytes({"ok": b"1", "a/../../x": b"x"}))
        with self.assertRaises(remote.Unsafe):
            remote.unpack(tar, self.tmp / "y")
        self.assertFalse((self.tmp / "y" / "ok").exists(), "nothing extracted from a refused archive")
        tar.write_bytes(b"not a tar")
        with self.assertRaises(remote.Unsafe):
            remote.unpack(tar, self.tmp / "y")
        # pack leaves links out of what it uploads
        src = self.tmp / "src"
        src.mkdir()
        (src / "f").write_text("f")
        os.symlink("/etc/passwd", src / "l")
        remote.pack(src, self.tmp / "p.tar", log)
        self.assertEqual(list(untar((self.tmp / "p.tar").read_bytes())), ["f"])
        self.assertIn(b"left out of p.tar: l", log.tail())

    def test_upload_failures_exit_4(self):
        self.store.fail["runs/r1/out.tar"] = 500
        self.assertEqual(self.run_remote(), 4)
        self.assertEqual(self.store.hits[("PUT", "runs/r1/out.tar")], remote.ATTEMPTS)
        self.assertIn("the job exited 0 but uploads failed: out", self.log())
        del self.store.fail["runs/r1/out.tar"]
        self.store.fail[("PUT", "data/test/b1.tar.gz")] = 403
        self.store.objects["data/test/b1.tar.gz"] = tar_bytes({"count.txt": b"7"}, gz=True)
        self.assertEqual(self.run_remote(), 4)
        rep = self.report()
        self.assertEqual((rep["exit_code"], rep["job_exit"], rep["uploads_failed"]), (4, 0, ["data"]))
        self.assertEqual(rep["data"]["status"], "failed")

    def test_log_failure_keeps_the_exit(self):
        self.store.fail["runs/r1/log"] = 500
        self.assertEqual(self.run_remote(), 0)
        self.assertIn("log upload failed", self.stdout)

    def test_log_is_the_last_64_kib(self):
        log = remote.Log(io.BytesIO())
        log.write(b"a" * remote.LOG_TAIL)
        log.say("the end")
        tail = log.tail()
        self.assertEqual(len(tail), remote.LOG_TAIL)
        self.assertTrue(tail.endswith(b"slowapp-remote: the end\n"))


    # ------------------------------------------------------------------ review fixes

    def test_broken_http_responses_are_retried_then_exit_4(self):
        for how, err in (("status", "BadStatusLine"), ("short", "IncompleteRead")):
            with self.subTest(how):
                self.store.hits.clear()
                self.store.garble["runs/r1/in.tar"] = how
                self.assertEqual(self.run_remote(), 4, self.stdout)
                self.assertEqual(self.store.hits[("GET", "runs/r1/in.tar")], remote.ATTEMPTS, "retried")
                rep = self.report()
                self.assertIsNone(rep["job_exit"])
                self.assertIn(err, rep["error"])
                self.assertNotIn("Traceback", self.stdout)
                self.assertIn("runs/r1/log", self.store.objects)

    def test_data_put_alone_never_overwrites(self):
        saved = tar_bytes({"count.txt": b"7"}, gz=True)
        self.store.objects["data/test/b1.tar.gz"] = saved
        self.assertEqual(self.run_remote(SLOWAPP_REMOTE_DATA_GET=None), 0, self.stdout)
        self.assertEqual(self.store.objects["data/test/b1.tar.gz"], saved)
        self.assertNotIn(("PUT", "data/test/b1.tar.gz"), self.store.hits)
        self.assertEqual(self.report()["data"], {"status": "none"})
        self.assertIn("DATA_PUT without DATA_GET or DATA_NEW=1", self.log())

    def test_data_new_starts_empty_and_saves(self):
        self.assertEqual(self.run_remote(SLOWAPP_REMOTE_DATA_GET=None, SLOWAPP_REMOTE_DATA_NEW="1"), 0, self.stdout)
        self.assertNotIn(("GET", "data/test/b1.tar.gz"), self.store.hits)
        self.assertEqual(self.data()["count.txt"], b"1")
        rep = self.report()
        self.assertEqual((rep["data"]["status"], rep["data"]["loaded"]), ("saved", False))

    def test_data_get_403_is_not_missing(self):
        self.store.fail[("GET", "data/test/b1.tar.gz")] = 403
        self.assertEqual(self.run_remote(SLOWAPP_REMOTE_DATA_NEW="1"), 4, "the GET decides when it's sent")
        self.assertNotIn(("PUT", "data/test/b1.tar.gz"), self.store.hits)

    def test_timeout_zero_or_less_is_no_limit(self):
        for raw in ("0", "-1", "inf", ""):
            with self.subTest(raw=raw):
                self.assertEqual(self.run_remote(SLOWAPP_REMOTE_TIMEOUT_S=raw), 0, self.stdout)
                self.assertEqual(self.report()["job_exit"], 0)
        self.assertEqual(remote._child_timeout({"SLOWAPP_REMOTE_TIMEOUT_S": " 2.5 "}), 2.5)

    def test_unparsable_timeout_exits_64(self):
        for raw in ("soon", "nan"):
            with self.subTest(raw=raw):
                self.assertEqual(self.run_remote(SLOWAPP_REMOTE_TIMEOUT_S=raw), 64, self.stdout)
                rep = self.report()
                self.assertIsNone(rep["job_exit"])
                self.assertIn("SLOWAPP_REMOTE_TIMEOUT_S", rep["error"])
        self.assertNotIn(("GET", "runs/r1/in.tar"), self.store.hits, "checked before any fetch")

    def test_job_that_wont_start(self):
        self.store.objects["data/test/b1.tar.gz"] = tar_bytes({"count.txt": b"7"}, gz=True)
        cmd = [sys.executable, "-m", "slowapp_kit.remote"]
        self.assertEqual(self.run_remote(cmd=cmd, SLOWAPP_ENTRYPOINT='["/nonexistent/app"]'), 64, self.stdout)
        rep = self.report()
        self.assertIsNone(rep["job_exit"])
        self.assertEqual(rep["exit_code"], 64)
        self.assertIn("couldn't start the job", rep["error"])
        self.assertEqual(rep["data"]["status"], "none")
        self.assertNotIn(("PUT", "data/test/b1.tar.gz"), self.store.hits)

    def stopped(self, sig, **kw):
        """Run the sleeping job, send the wrapper sig once the job is asleep, return its exit."""
        self.settings(dict({"sleep": 30}, **kw.pop("settings", {})))
        p = subprocess.Popen(APP + ["slowapp-remote", "job", "remote"], env=self.env(**kw),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        seen = b""
        while b"remote job: sleeping" not in seen:
            line = p.stdout.readline()
            self.assertTrue(line, seen.decode())
            seen += line
        p.send_signal(sig)
        seen += p.communicate(timeout=30)[0]
        self.stdout = seen.decode()
        return p.returncode

    def test_sigterm_stops_the_job_and_still_uploads(self):
        self.assertEqual(self.stopped(signal.SIGTERM), 143, self.stdout)
        rep = self.report()
        self.assertEqual((rep["exit_code"], rep["job_exit"]), (143, 143))
        self.assertEqual(rep["error"], "stopped by SIGTERM")
        self.assertEqual(rep["data"]["status"], "saved", "what the job left in /data is kept")
        self.assertEqual(self.data()["count.txt"], b"1")
        self.assertIn("slowapp-remote: exit 143", self.log())

    def test_sigint_kills_a_job_that_ignores_sigterm(self):
        code = self.stopped(signal.SIGINT, settings={"ignore_term": True}, SLOWAPP_REMOTE_STOP_GRACE_S="0.5")
        self.assertEqual(code, 130, self.stdout)
        rep = self.report()
        self.assertEqual((rep["exit_code"], rep["job_exit"]), (130, 137))
        self.assertEqual(rep["error"], "stopped by SIGINT")
        self.assertIn("slowapp-remote: exit 130", self.log())

    def test_pack_writes_hard_links_as_files(self):
        src = self.tmp / "src"
        (src / "a").mkdir(parents=True)
        (src / "a" / "f").write_text("same")
        os.link(src / "a" / "f", src / "g")
        os.link(src / "a" / "f", src / "a" / "h")
        remote.pack(src, self.tmp / "p.tar", remote.Log(io.BytesIO()))
        with tarfile.open(self.tmp / "p.tar") as tf:
            members = tf.getmembers()
        self.assertEqual([m.name for m in members], ["a", "g", "a/f", "a/h"], "sorted, each dir's own first")
        for m in members[1:]:
            self.assertEqual((m.type, m.linkname, m.size), (tarfile.REGTYPE, "", 4), m.name)
        out = untar((self.tmp / "p.tar").read_bytes())
        self.assertEqual(out, {"g": b"same", "a/f": b"same", "a/h": b"same"})

    def test_bad_entrypoint_exits_64_on_both_paths(self):
        standalone = [sys.executable, "-m", "slowapp_kit.remote"]
        for raw in ("not json", '"python3"', "[]", "[1]", '[""]', '{"a": 1}'):
            for cmd in (standalone, APP + ["slowapp-remote"]):
                with self.subTest(raw=raw, cmd=cmd[-1]):
                    self.assertEqual(self.run_remote(cmd=cmd, SLOWAPP_ENTRYPOINT=raw), 64, self.stdout)
                    self.assertNotIn("Traceback", self.stdout)
                    rep = self.report()
                    self.assertIsNone(rep["job_exit"])
                    self.assertIn("SLOWAPP_ENTRYPOINT must be a non-empty JSON list", rep["error"])

    def test_jobs_entrypoint_shares_the_parser(self):
        with mock.patch.dict(os.environ, {"SLOWAPP_ENTRYPOINT": '["python3", "-m", "moon"]'}):
            self.assertEqual(jobs.entrypoint(), ["python3", "-m", "moon"])
        with mock.patch.dict(os.environ, {"SLOWAPP_ENTRYPOINT": "[1]"}):
            with self.assertRaises(ContractError):
                jobs.entrypoint()
            code, msg = jobs.run_in_child("remote")
            self.assertEqual(code, 64)
            self.assertIn("SLOWAPP_ENTRYPOINT", msg)

    def test_permanent_errors_are_not_retried(self):
        log = remote.Log(io.BytesIO())
        permanent = [FileNotFoundError(2, "no such file"), PermissionError(13, "denied"), ValueError("bad"),
                     urllib.error.URLError("unknown url type: ftpx"),
                     urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed")),
                     urllib.error.URLError(FileNotFoundError(2, "no such file"))]
        transient = [ConnectionRefusedError(), TimeoutError(), urllib.error.URLError(ConnectionResetError()),
                     urllib.error.URLError(ssl.SSLError(1, "handshake")), http.client.IncompleteRead(b""),
                     http.client.BadStatusLine("x")]
        with mock.patch.object(remote, "RETRY_S", 0):
            for e in permanent + transient:
                with self.subTest(e=repr(e)):
                    calls = []

                    def fn():
                        calls.append(1)
                        raise e
                    with self.assertRaises(type(e)):
                        remote._attempts("x", log, fn)
                    self.assertEqual(len(calls), 1 if e in permanent else remote.ATTEMPTS)
            # a local file that can't be written: one try
            with self.assertRaises(FileNotFoundError):
                remote.get(self.store.url("runs/r1/in.tar"), self.tmp / "no" / "in.tar", "in.tar", log)
        self.assertEqual(self.store.hits[("GET", "runs/r1/in.tar")], 1)
        self.assertEqual(self.run_remote(SLOWAPP_REMOTE_IN="ftpx://example/in.tar"), 4)
        self.assertNotIn("retry", self.log())
        self.assertIn("unknown url type", self.report()["error"])

    def test_put_bytes_sends_the_bytes(self):
        with mock.patch.object(remote.tempfile, "mkstemp", side_effect=AssertionError("no temp file")):
            n = remote.put_bytes(self.store.url("runs/r1/log"), b"hello", "log", "log upload",
                                 remote.Log(io.BytesIO()))
        self.assertEqual(n, 5)
        self.assertEqual(self.store.objects["runs/r1/log"], b"hello")
        self.assertEqual(self.store.types["runs/r1/log"], "text/plain; charset=utf-8")
        self.assertEqual(self.store.chunked, [])

    # ------------------------------------------------------------------ the standalone command

    def test_standalone_with_entrypoint(self):
        cmd = [sys.executable, "-m", "slowapp_kit.remote"]
        self.assertEqual(self.run_remote(cmd=cmd, SLOWAPP_ENTRYPOINT=json.dumps(APP)), 0, self.stdout)
        self.assertEqual(self.report()["job_exit"], 0)
        self.assertEqual(self.run_remote(cmd=cmd), 64)
        self.assertIn("SLOWAPP_ENTRYPOINT", self.report()["error"])
        self.assertIn("SLOWAPP_ENTRYPOINT", self.log())

    def test_usage(self):
        self.assertEqual(remote.run(["serve"], entry=APP, log=remote.Log(io.BytesIO())), 64)


# ---------------------------------------------------------------------- sealed runs (contract 6)

def b64(b):
    return base64.b64encode(b).decode()


class Sealed(RemoteBase):
    """SLOWAPP_REMOTE_KEY_FILE: in.tar and the saved data open with the run's keys; out.tar,
    data.tar.gz and the log go back sealed; the key file is gone before the job starts."""

    def setUp(self):
        super().setUp()
        self.key, self.data_key = os.urandom(32), os.urandom(32)
        self.seal_in()

    def seal_in(self, key=None, label="in"):
        o = self.store.objects
        o["runs/r1/in.tar"] = seal.seal_bytes(key or self.key, label, o["runs/r1/in.tar"])

    def settings(self, settings, files=None):
        super().settings(settings, files)
        if hasattr(self, "key"):
            self.seal_in()

    def run_sealed(self, job="remote", content=None, **kw):
        self.kf = self.tmp / f"key-{uuid.uuid4().hex[:6]}"
        self.kf.write_text(content if content is not None else
                           json.dumps({"key": b64(self.key), "data_key": b64(self.data_key)}))
        return self.run_remote(job, SLOWAPP_REMOTE_KEY_FILE=str(self.kf), **kw)

    def out(self):
        return untar(seal.open_bytes(self.key, "out", self.store.objects["runs/r1/out.tar"]))

    def log(self):
        return seal.open_bytes(self.key, "log", self.store.objects["runs/r1/log"]).decode()

    def data(self):
        return untar(seal.open_bytes(self.data_key, "data", self.store.objects["data/test/b1.tar.gz"]))

    def test_a_sealed_run(self):
        self.settings({"hello": "there"})
        self.assertEqual(self.run_sealed(), 0, self.stdout)
        self.assertFalse(self.kf.exists(), "the key file is deleted before the job runs")
        seen = json.loads(self.out()["seen.json"])
        self.assertEqual(seen["settings"], {"hello": "there"})
        self.assertEqual(seen["remote_env"], [])
        rep = self.report()
        self.assertTrue(rep["sealed"])
        self.assertEqual((rep["exit_code"], rep["data"]["status"]), (0, "saved"))
        self.assertEqual(self.data()["count.txt"], b"1")
        s = self.store
        for k in ("runs/r1/out.tar", "runs/r1/log", "data/test/b1.tar.gz"):
            self.assertEqual(s.types[k], "application/octet-stream", k)
            self.assertTrue(s.objects[k].startswith(seal.MAGIC), k)
            for plain in (b"remote job", b"hello", b"seen.json", b"count.txt"):
                self.assertNotIn(plain, s.objects[k], f"{plain} in {k}")
        # The job's output is in the sealed log only; the machine's log has the wrapper's lines.
        self.assertIn("remote job: to stdout", self.log())
        self.assertIn("slowapp-remote: exit 0", self.log())
        self.assertNotIn("remote job:", self.stdout)
        self.assertIn("slowapp-remote: exit 0", self.stdout)
        self.assertIn("sealed run", self.stdout)

    def test_sealed_data_carries_over_under_the_data_key(self):
        self.assertEqual(self.run_sealed(), 0, self.stdout)
        self.key = os.urandom(32)                   # a new run, a new run key; the same data key
        self.settings({})
        self.assertEqual(self.run_sealed(), 0, self.stdout)
        self.assertEqual(self.data()["count.txt"], b"2")
        self.assertTrue(self.report()["data"]["loaded"])

    def test_one_key_for_everything(self):
        self.data_key = self.key
        self.assertEqual(self.run_sealed(content=b64(self.key) + "\n"), 0, self.stdout)
        self.assertEqual(self.data()["count.txt"], b"1")
        self.assertEqual(self.run_sealed(content=b64(self.key)), 0, self.stdout)
        self.assertEqual(self.data()["count.txt"], b"2")

    def test_an_input_that_doesnt_open_is_refused(self):
        o = self.store.objects
        good = o["runs/r1/in.tar"]
        for why, body in (("tampered", good[:40] + bytes([good[40] ^ 1]) + good[41:]),
                          ("cut short", good[:-1]),
                          ("plain", tar_bytes({"settings.json": b"{}"})),
                          ("another label", seal.seal_bytes(self.key, "out", tar_bytes({"settings.json": b"{}"}))),
                          ("another key", seal.seal_bytes(os.urandom(32), "in", tar_bytes({"settings.json": b"{}"})))):
            with self.subTest(why):
                o["runs/r1/in.tar"] = body
                self.assertEqual(self.run_sealed(), 4, self.stdout)
                rep = self.report()
                self.assertIsNone(rep["job_exit"])
                self.assertIn("in.tar doesn't open with the run's key", rep["error"])
                self.assertNotIn("data/test/b1.tar.gz", o, "the job didn't run: /data isn't saved")

    def test_saved_data_that_doesnt_open_is_refused(self):
        self.assertEqual(self.run_sealed(), 0, self.stdout)
        o = self.store.objects
        o["data/test/b1.tar.gz"] = o["data/test/b1.tar.gz"][:-20]
        self.settings({})
        self.assertEqual(self.run_sealed(), 4, self.stdout)
        self.assertIn("data doesn't open", self.report()["error"])

    def test_bad_key_files_exit_64(self):
        for why, content in (("not base64", "!!!"), ("short", b64(b"x" * 16)),
                             ("json without key", '{"data_key": "' + b64(self.key) + '"}'),
                             ("bad data_key", json.dumps({"key": b64(self.key), "data_key": "AAAA"}))):
            with self.subTest(why):
                self.assertEqual(self.run_sealed(content=content), 64, self.stdout)
                self.assertFalse(self.kf.exists())
                # Nothing to seal with: out.tar holds only the wrapper's report, in the clear.
                rep = json.loads(untar(self.store.objects["runs/r1/out.tar"])[".remote.json"])
                self.assertIn("SLOWAPP_REMOTE_KEY_FILE", rep["error"])
                self.assertIsNone(rep["job_exit"])
        self.assertEqual(self.run_remote(SLOWAPP_REMOTE_KEY_FILE=str(self.tmp / "nope")), 64)

    def test_read_keys(self):
        f = self.tmp / "k"
        f.write_text(json.dumps({"key": b64(self.key)}))
        self.assertEqual(remote.read_keys({"SLOWAPP_REMOTE_KEY_FILE": str(f)}), {"key": self.key, "data": self.key})
        self.assertFalse(f.exists())
        self.assertIsNone(remote.read_keys({}))


# ---------------------------------------------------------------------- no network (contract 6)

C6 = """[app]
id = "test"
contract = 6
network = "{app_net}"
[[job]]
name = "net"
{job}
"""


class Network(RemoteBase):
    """A job that should have no network runs in an empty network namespace, once its inputs are
    in. Needs Linux and root with CAP_SYS_ADMIN (a Fly Machine; Docker --privileged): elsewhere
    the wrapper says so loudly and runs it with the network. SLOWAPP_TEST_NETNS=1 makes that a
    failure (the privileged Docker run)."""

    def manifest(self, text):
        p = self.tmp / "slowapp.toml"
        p.write_text(text)
        return str(p)

    def run_net(self, text, **kw):
        port = self.store.server_address[1]
        code = self.run_remote("net", SLOWAPP_MANIFEST=self.manifest(text),
                               SLOWAPP_TEST_REACH=f"127.0.0.1:{port}", **kw)
        self.assertEqual(code, 0, self.stdout)
        return json.loads(self.out()["net.json"]), self.report()["network"]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import warnings
        with warnings.catch_warnings():             # the probe forks; this process has threads
            warnings.simplefilter("ignore", DeprecationWarning)
            cls.why = remote.netns_unavailable()

    def assert_isolated(self, net, rep):
        self.assertEqual(rep["wanted"], "none")
        if self.why is None:
            self.assertEqual(rep, {"wanted": "none", "isolated": True, "error": None})
            # A new namespace: lo, and the kernel's fallback tunnels (gre0, tunl0, …), which are
            # down. No route anywhere, and the store the wrapper just used is out of reach.
            self.assertIn("lo", net["ifaces"])
            self.assertNotIn("eth0", net["ifaces"])
            self.assertEqual(net["routes"], [], "no IPv4 route")
            self.assertIsNot(net["reach"], True, "the job reached the store")
            self.assertIn("no network (an empty network namespace)", self.log())
        else:
            if os.environ.get("SLOWAPP_TEST_NETNS") == "1":
                self.fail(f"SLOWAPP_TEST_NETNS=1, but: {self.why}")
            self.assertFalse(rep["isolated"])
            self.assertTrue(rep["error"])
            self.assertIn("WARNING: job net should run without the network", self.log())
            self.assertIn("WARNING", self.stdout)

    def test_a_render_job_has_no_network(self):
        self.assert_isolated(*self.run_net(C6.format(app_net="egress", job="")))
        # The wrapper's own uploads still went out.
        self.assertIn("net.json", self.out())
        self.assertIn(b"slowapp-remote: exit 0", self.store.objects["runs/r1/log"])

    def test_a_sync_job_keeps_its_network(self):
        net, rep = self.run_net(C6.format(app_net="none", job='kind = "sync"\nnetwork = "egress"'))
        self.assertEqual(rep, {"wanted": "egress", "isolated": False, "error": None})
        self.assertIs(net["reach"], True)
        self.assert_isolated(*self.run_net(C6.format(app_net="egress", job='kind = "sync"\nnetwork = "none"')))
        self.assert_isolated(*self.run_net(C6.format(app_net="none", job='kind = "sync"')))

    def test_before_contract_6_the_apps_network(self):
        c5 = C6.replace("contract = 6", "contract = 5")
        net, rep = self.run_net(c5.format(app_net="egress", job=""))
        self.assertEqual((rep["wanted"], net["reach"]), ("egress", True), "weather's render keeps the network")
        self.assert_isolated(*self.run_net(c5.format(app_net="none", job="")))
        # No manifest to go by: as before contract 6.
        self.assertEqual(self.run_remote("net", SLOWAPP_TEST_REACH=f"127.0.0.1:{self.store.server_address[1]}"), 0)
        self.assertEqual(self.report()["network"]["wanted"], "egress")

    def test_the_hub_can_say_none(self):
        c5 = C6.replace("contract = 6", "contract = 5").format(app_net="egress", job="")
        self.assert_isolated(*self.run_net(c5, SLOWAPP_REMOTE_NETWORK="none"))
        net, rep = self.run_net(C6.format(app_net="egress", job=""), SLOWAPP_REMOTE_NETWORK="egress")
        self.assertEqual(rep["wanted"], "none", "egress from the hub doesn't loosen render")
        self.assertEqual(self.run_remote("net", SLOWAPP_REMOTE_NETWORK="lan"), 64)

    def test_sealed_and_isolated(self):
        key = os.urandom(32)
        o = self.store.objects
        o["runs/r1/in.tar"] = seal.seal_bytes(key, "in", o["runs/r1/in.tar"])
        kf = self.tmp / "key"
        kf.write_text(b64(key))
        port = self.store.server_address[1]
        code = self.run_remote("net", SLOWAPP_MANIFEST=self.manifest(C6.format(app_net="egress", job="")),
                               SLOWAPP_TEST_REACH=f"127.0.0.1:{port}", SLOWAPP_REMOTE_KEY_FILE=str(kf),
                               SLOWAPP_TEST_KEY_PATH=str(kf))
        self.assertEqual(code, 0, self.stdout)
        out = untar(seal.open_bytes(key, "out", o["runs/r1/out.tar"]))
        net = json.loads(out["net.json"])
        self.assertEqual((net["key_file"], net["key_file_exists"]), (None, False))
        self.assertTrue(json.loads(out[".remote.json"])["sealed"])


# ---------------------------------------------------------------------- a real S3 API

def presign(method, endpoint, path, access, secret, region="us-east-1", expires=900):
    """A SigV4 query-signed link (host the only signed header, payload unsigned): what the hub's
    Tigris store signs."""
    u = urllib.parse.urlsplit(endpoint)
    amz = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scope = f"{amz[:8]}/{region}/s3/aws4_request"
    q = {"X-Amz-Algorithm": "AWS4-HMAC-SHA256", "X-Amz-Credential": f"{access}/{scope}", "X-Amz-Date": amz,
         "X-Amz-Expires": str(expires), "X-Amz-SignedHeaders": "host"}
    query = "&".join(f"{urllib.parse.quote(k, safe='~')}={urllib.parse.quote(v, safe='~')}"
                     for k, v in sorted(q.items()))
    path = urllib.parse.quote(path, safe="/~")
    creq = "\n".join([method, path, query, f"host:{u.netloc}\n", "host", "UNSIGNED-PAYLOAD"])
    sts = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(creq.encode()).hexdigest()])
    key = ("AWS4" + secret).encode()
    for part in (amz[:8], region, "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    sig = hmac.new(key, sts.encode(), hashlib.sha256).hexdigest()
    return f"{u.scheme}://{u.netloc}{path}?{query}&X-Amz-Signature={sig}"


S3 = os.environ.get("SLOWAPP_TEST_S3")


@unittest.skipUnless(S3, "SLOWAPP_TEST_S3 (an S3 endpoint; CI runs versitygw) isn't set")
class S3Links(unittest.TestCase):
    def setUp(self):
        self.key, self.secret = os.environ["SLOWAPP_TEST_S3_KEY"], os.environ["SLOWAPP_TEST_S3_SECRET"]
        self.bucket = f"sb-test-{uuid.uuid4().hex[:8]}"
        self.tmp = Path(tempfile.mkdtemp())
        self.req("PUT", f"/{self.bucket}")

    def link(self, method, name):
        return presign(method, S3, f"/{self.bucket}/{name}", self.key, self.secret)

    def req(self, method, path, body=None):
        url = presign(method, S3, path, self.key, self.secret)
        r = urllib.request.Request(url, data=body, method=method,
                                   headers={"Content-Length": str(len(body or b""))} if method == "PUT" else {})
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.read()

    def test_a_run_through_s3(self):
        self.req("PUT", f"/{self.bucket}/runs/r1/in.tar", tar_bytes({"settings.json": b'{"hi": 1}'}))
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLOWAPP_")}
        env.update(SLOWAPP_CONTRACT="5", SLOWAPP_APP="test", SLOWAPP_RUN_ID="r1", SLOWAPP_FEEDS=FEEDS,
                   SLOWAPP_MANIFEST=str(self.tmp / "none.toml"), SLOWAPP_JOB_LOCK=str(self.tmp / "lock"),
                   SLOWAPP_REMOTE_RETRY_S="0", SLOWAPP_REMOTE_DATA_MAX_MB="1",
                   SLOWAPP_REMOTE_IN=self.link("GET", "runs/r1/in.tar"),
                   SLOWAPP_REMOTE_OUT=self.link("PUT", "runs/r1/out.tar"),
                   SLOWAPP_REMOTE_LOG=self.link("PUT", "runs/r1/log"),
                   SLOWAPP_REMOTE_DATA_GET=self.link("GET", "data/test/b1.tar.gz"),
                   SLOWAPP_REMOTE_DATA_PUT=self.link("PUT", "data/test/b1.tar.gz"))
        for n in (1, 2):
            p = subprocess.run(APP + ["slowapp-remote", "job", "remote"], env=env, capture_output=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stdout.decode())
            out = untar(self.req("GET", f"/{self.bucket}/runs/r1/out.tar"))
            self.assertEqual(json.loads(out["seen.json"])["settings"], {"hi": 1})
            self.assertEqual(json.loads(out[".remote.json"])["exit_code"], 0)
            self.assertIn(".metrics.json", out)
            self.assertEqual(untar(self.req("GET", f"/{self.bucket}/data/test/b1.tar.gz"))["count.txt"],
                             str(n).encode(), "the first run's GET is S3's 404: start empty")
            self.assertIn(b"slowapp-remote: exit 0", self.req("GET", f"/{self.bucket}/runs/r1/log"))

    def test_a_sealed_run_through_s3(self):
        key = os.urandom(32)
        self.req("PUT", f"/{self.bucket}/runs/r1/in.tar", seal.seal_bytes(key, "in", tar_bytes({"settings.json": b'{"hi": 1}'})))
        kf = self.tmp / "key"
        kf.write_text(b64(key))
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLOWAPP_")}
        env.update(SLOWAPP_CONTRACT="5", SLOWAPP_APP="test", SLOWAPP_RUN_ID="r1", SLOWAPP_FEEDS=FEEDS,
                   SLOWAPP_MANIFEST=str(self.tmp / "none.toml"), SLOWAPP_JOB_LOCK=str(self.tmp / "lock"),
                   SLOWAPP_REMOTE_RETRY_S="0", SLOWAPP_REMOTE_DATA_NEW="1", SLOWAPP_REMOTE_KEY_FILE=str(kf),
                   SLOWAPP_REMOTE_IN=self.link("GET", "runs/r1/in.tar"),
                   SLOWAPP_REMOTE_OUT=self.link("PUT", "runs/r1/out.tar"),
                   SLOWAPP_REMOTE_LOG=self.link("PUT", "runs/r1/log"),
                   SLOWAPP_REMOTE_DATA_PUT=self.link("PUT", "data/test/b1.tar.gz"))
        p = subprocess.run(APP + ["slowapp-remote", "job", "remote"], env=env, capture_output=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout.decode())
        out = untar(seal.open_bytes(key, "out", self.req("GET", f"/{self.bucket}/runs/r1/out.tar")))
        self.assertEqual(json.loads(out["seen.json"])["settings"], {"hi": 1})
        data = untar(seal.open_bytes(key, "data", self.req("GET", f"/{self.bucket}/data/test/b1.tar.gz")))
        self.assertEqual(data["count.txt"], b"1")
        self.assertIn(b"remote job: to stdout", seal.open_bytes(key, "log", self.req("GET", f"/{self.bucket}/runs/r1/log")))


if __name__ == "__main__":
    unittest.main()
