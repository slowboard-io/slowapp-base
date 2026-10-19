"""slowapp_kit unit tests. Import paths come from the caller, so the kit under test is whichever
slowapp_kit PYTHONPATH finds first:

  repo:   PYTHONPATH=kit python3 -m unittest discover -s kit/tests
  image:  docker run -v "$PWD:/src:ro" -e PYTHONPATH=/opt/slowapp slowapp-python:dev \
            python3 -m unittest discover -s /src/kit/tests
"""
import hashlib
import http.client
import io
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent

import slowapp_kit as kit  # noqa: E402
from slowapp_kit import BLACK, RED, WHITE, YELLOW, Card  # noqa: E402

FEEDS = json.dumps([{"feed": "left", "slot": "left", "w": 452, "h": 444, "inks": "k4", "bpp": 2, "key": "red"},
                    {"feed": "middle", "slot": "middle", "w": 456, "h": 444, "inks": "k4", "bpp": 2, "key": "yellow"}])


def drawn(w=452, h=444):
    img = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((10, 10, 100, 60), fill=RED)
    d.rectangle((120, 10, 200, 60), fill=YELLOW)
    d.line((0, 300, w - 1, 300), fill=BLACK, width=3)
    return img


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for d in ("data", "out", "in", "secrets"):
            (self.tmp / d).mkdir()
        self.env = dict(SLOWAPP_CONTRACT="3", SLOWAPP_APP="test", SLOWAPP_JOB="render", SLOWAPP_RUN_ID="r_1",
                        SLOWAPP_MODE="live", SLOWAPP_NOW="2026-10-06T09:00:00-07:00", TZ="America/Vancouver",
                        SLOWAPP_FEEDS=FEEDS, SLOWAPP_STATE=str(self.tmp / "data"), SLOWAPP_OUT=str(self.tmp / "out"),
                        SLOWAPP_IN=str(self.tmp / "in"), SLOWAPP_SECRETS=str(self.tmp / "secrets"),
                        SLOWAPP_MANIFEST=str(self.tmp / "slowapp.toml"))

    def ctx(self, **kw):
        return kit.Context.from_env(env=dict(self.env, **kw))


class Inks(unittest.TestCase):
    def test_off_palette_pixels_raise(self):
        img = drawn()
        img.putpixel((5, 5), (128, 128, 128))
        with self.assertRaises(kit.InkError):
            kit.check_inks(img)

    def test_a_many_coloured_picture_raises_without_a_big_table(self):
        from PIL import Image
        img = Image.new("RGB", (64, 64))
        img.putdata([(i % 256, i // 256, 7) for i in range(64 * 64)])
        with self.assertRaises(kit.InkError):
            kit.check_inks(img)
        with self.assertRaises(kit.InkError):
            kit.check_inks(img, "g16")

    def test_encoded_png_meets_the_bundle_rules(self):
        data = kit.encode_png(drawn())
        self.assertEqual(data[24], 2, "bit depth 2")
        self.assertEqual(data[25], 3, "indexed")
        self.assertNotIn(b"tRNS", data)
        plte = data.index(b"PLTE")
        self.assertEqual(struct.unpack(">I", data[plte - 4:plte])[0], 12, "PLTE is exactly the four inks")
        rgb = kit.check_png(data, (452, 444))
        self.assertEqual(rgb.tobytes(), drawn().tobytes())

    def test_check_png_rejects_rgb_and_wrong_size(self):
        buf = io.BytesIO()
        drawn().save(buf, "PNG")
        with self.assertRaises(kit.InkError):
            kit.check_png(buf.getvalue())
        with self.assertRaises(kit.InkError):
            kit.check_png(kit.encode_png(drawn()), (456, 444))

    def test_pack_matches_epd_pack_order(self):
        img = Image.new("RGB", (8, 1), WHITE)
        for x, c in enumerate([BLACK, WHITE, YELLOW, RED, RED, YELLOW, WHITE, BLACK]):
            img.putpixel((x, 0), c)
        self.assertEqual(kit.pack_rows(img), bytes([0b00011011, 0b11100100]))

    def test_blob_id_is_sbp2_over_packed_rows(self):
        img = drawn()
        want = hashlib.sha256(b"SBP2" + struct.pack("<HH", 452, 444) + kit.pack_rows(img)).hexdigest()
        self.assertEqual(kit.blob_id(img), want)
        self.assertEqual(kit.blob_id(kit.encode_png(img)), want, "same id from the PNG")
        img.putpixel((0, 0), RED)
        self.assertNotEqual(kit.blob_id(img), want)

    def test_blob_id_golden(self):
        # Checked against the dashboard's epd.pack.pack_region on 2026-10-07; sb-proto pins the
        # same SBP2 packing on the hub side.
        self.assertEqual(kit.blob_id(drawn()), "39823036768f21053e5657354fd2aa883354868439b33892fbdbc99abb39d51f")


class ContextTests(Env):
    def test_reads_the_environment(self):
        c = self.ctx()
        self.assertEqual((c.app, c.job, c.run_id, c.mode), ("test", "render", "r_1", "live"))
        self.assertEqual([s.name for s in c.feeds], ["452x444.k4", "456x444.k4"])
        self.assertEqual(c.feed("middle").key, "yellow")
        self.assertIsNone(c.feed("right"))
        self.assertEqual(c.now.utcoffset().total_seconds(), -7 * 3600)

    def test_fixture_needs_a_fixed_now(self):
        env = dict(self.env, SLOWAPP_MODE="fixture")
        del env["SLOWAPP_NOW"]
        with self.assertRaises(kit.ContractError):
            kit.Context.from_env(env=env)

    def test_settings_defaults_from_the_manifest(self):
        (self.tmp / "slowapp.toml").write_text('[app]\nid="test"\n[settings]\nlookahead_days = { type = "number", default = 14 }\n')
        self.assertEqual(self.ctx().settings, {"lookahead_days": 14})
        (self.tmp / "in" / "settings.json").write_text('{"lookahead_days": 3}')
        self.assertEqual(self.ctx().settings, {"lookahead_days": 3})


class Output(Env):
    def test_write_feed(self):
        c = self.ctx()
        deck = c.write_feed("left", [Card("home", drawn(), "GFA now", "Rain from 14h"),
                                     Card("gfa6", drawn(), "GFA +6 h", keep_s=600)])
        root = self.tmp / "out" / "feeds" / "left"
        on_disk = json.loads((root / "deck.json").read_text())
        self.assertEqual(on_disk, deck)
        self.assertEqual([x["kind"] for x in deck["cards"]], ["home", "detail"])
        self.assertEqual(deck["cards"][1]["keep_s"], 600)
        self.assertEqual(deck["valid_from"], "2026-10-06T09:00:00-07:00")
        self.assertEqual(deck["valid_until"], "2026-10-06T10:00:00-07:00")
        kit.check_png((root / "cards" / "gfa6.png").read_bytes(), (452, 444))

    def test_write_feed_rejects_bad_cards(self):
        c = self.ctx()
        for cards in ([Card("home", drawn(456), "x")],                      # wrong size
                      [Card("Home", drawn(), "x")],                         # bad id
                      [Card("home", drawn(), "")],                          # no title
                      [Card("a", drawn(), "x"), Card("a", drawn(), "y")],   # duplicate
                      [Card("a", drawn(), "x", kind="detail")]):            # first isn't home
            with self.assertRaises(kit.ContractError):
                c.write_feed("left", cards)
        bad = drawn()
        bad.putpixel((1, 1), (1, 2, 3))
        with self.assertRaises(kit.ContractError):
            c.write_feed("left", [Card("home", bad, "x")])
        with self.assertRaises(kit.ContractError):
            c.write_feed("right", [Card("home", drawn(), "x")])

    def test_summary_and_timing(self):
        c = self.ctx()
        c.write_summary("ok", ["17°"], [{"label": "Update", "job": "render"}])
        c.write_timing(c.now)
        self.assertEqual(json.loads((self.tmp / "out" / "summary.json").read_text())["actions"][0]["job"], "render")
        self.assertIn("next_change_at", json.loads((self.tmp / "out" / "timing.json").read_text()))
        with self.assertRaises(kit.ContractError):
            c.write_summary("ok", [], [{"label": "x"}])

    def prompt(self, **kw):
        p = {"id": "rem-42@2026-10-06T09:00@2026-10-06T09:00", "group": "rem-42",
             "from": "2026-10-06T09:00:00-07:00", "until": "2026-10-06T17:30:00-07:00",
             "question": "Water the plants?",
             "bindings": {"own.tap": {"image": drawn(), "strip": "Done",
                                      "emit": {"kind": "answer", "data": {"answer": "yes"}}}}}
        p.update(kw)
        return p

    def prompts_ctx(self, grant=True):
        (self.tmp / "slowapp.toml").write_text(f'[app]\nid = "test"\nprompts = {str(grant).lower()}\n')
        return self.ctx(SLOWAPP_FEEDS=json.dumps([{"feed": "prompts", "w": 452, "h": 444}]))

    def test_prompts(self):
        c = self.prompts_ctx()
        c.write_prompts([self.prompt()])
        doc = json.loads((self.tmp / "out" / "prompts.json").read_text())
        rel = doc["prompts"][0]["bindings"]["own.tap"]["show"]
        self.assertEqual(rel, "prompts/rem-42@2026-10-06T09:00@2026-10-06T09:00/own.tap.png")
        kit.check_png((self.tmp / "out" / rel).read_bytes(), (452, 444))

    def test_prompts_need_the_grant(self):
        with self.assertRaises(kit.ContractError):
            self.prompts_ctx(grant=False).write_prompts([self.prompt()])

    def test_bad_prompts(self):
        c = self.prompts_ctx()
        bad_ink = drawn()
        bad_ink.putpixel((0, 0), (9, 9, 9))
        for p in (self.prompt(id="a/b"), self.prompt(id=".hidden"), self.prompt(id="x" * 97),
                  self.prompt(id="sp ace"), self.prompt(group=""), self.prompt(question=None),
                  self.prompt(bindings={}), self.prompt(until="2026-10-06T09:00:00-07:00"),
                  self.prompt(bindings={"own.poke": {"image": drawn()}}),
                  self.prompt(bindings={"own.tap": {"image": drawn(456)}}),
                  self.prompt(bindings={"own.tap": {"image": bad_ink}}),
                  {k: v for k, v in self.prompt().items() if k != "from"}):
            with self.assertRaises(kit.ContractError, msg=str(p.get("id"))):
                c.write_prompts([p])
        with self.assertRaises(kit.ContractError):
            c.write_prompts([self.prompt(), self.prompt()])             # duplicate id


class Contract4(Env):
    """Docs, args and results (app UIs)."""

    def test_contracts_3_to_5_and_no_other(self):
        self.assertEqual(self.ctx(SLOWAPP_CONTRACT="3").app, self.ctx(SLOWAPP_CONTRACT="5").app)
        with self.assertRaises(kit.ContractError):
            self.ctx(SLOWAPP_CONTRACT="6")

    def test_args_and_docs_from_in(self):
        ctx = self.ctx()
        self.assertEqual((ctx.args, ctx.docs, ctx.doc("tags", {})), ({}, {}, {}))
        inp = Path(self.env["SLOWAPP_IN"])
        (inp / "docs").mkdir(parents=True, exist_ok=True)
        (inp / "args.json").write_text('{"url": "https://x"}')
        (inp / "docs" / "tags.json").write_text('{"work": "important"}')
        ctx = self.ctx()
        self.assertEqual(ctx.args, {"url": "https://x"})
        self.assertEqual(ctx.docs, {"tags": {"work": "important"}})
        self.assertEqual(ctx.doc("tags"), {"work": "important"})

    def test_write_doc_and_result(self):
        ctx = self.ctx()
        ctx.manifest = {"docs": {"tags": {}, "notes": {"writer": "ui"}}}
        ctx.write_doc("tags", {"a": 1})
        ctx.result({"ok": True, "n": 2})
        out = Path(self.env["SLOWAPP_OUT"])
        self.assertEqual(json.loads((out / "docs" / "tags.json").read_text()), {"a": 1})
        self.assertEqual(json.loads((out / "result.json").read_text()), {"ok": True, "n": 2})
        for bad in ("notes", "other", "Bad-Name"):
            with self.assertRaises(kit.ContractError, msg=bad):
                ctx.write_doc(bad, 1)
        with self.assertRaises(kit.ContractError):
            ctx.result("x" * (300 * 1024))


SLEEP = json.dumps([{"feed": "sleep", "w": 1360, "h": 360, "inks": "g16", "bpp": 8}])
DEVICE = json.dumps({"id": "d_x", "profile": "supernote", "w": 1404, "h": 1872, "inks": "g16"})


def greyed(w=1360, h=360):
    img = Image.new("RGB", (w, h), kit.grey(15))
    d = ImageDraw.Draw(img)
    d.rectangle((10, 10, 300, 100), fill=kit.grey(0))
    d.rectangle((320, 10, 600, 100), fill=kit.grey(8))
    return img


class Contract5(Env):
    """g16 feeds for other glass, and the device a run draws for."""

    def test_device_and_g16_feeds_from_the_environment(self):
        ctx = self.ctx(SLOWAPP_CONTRACT="5", SLOWAPP_FEEDS=SLEEP, SLOWAPP_DEVICE=DEVICE)
        self.assertEqual(ctx.device, kit.Device("d_x", "supernote", 1404, 1872, "g16"))
        self.assertEqual(ctx.feed("sleep").name, "1360x360.g16")
        self.assertIsNone(self.ctx().device, "no SLOWAPP_DEVICE: an older hub or fixture mode")
        with self.assertRaises(kit.ContractError):
            self.ctx(SLOWAPP_DEVICE="{}")

    def test_g16_png_is_8_bit_grey_on_the_levels(self):
        data = kit.encode_png(greyed(), "g16")
        self.assertEqual((data[24], data[25]), (8, 0), "8-bit grey")
        self.assertNotIn(b"PLTE", data)
        rgb = kit.check_png(data, (1360, 360), "g16")
        self.assertEqual(rgb.getpixel((20, 20)), (0, 0, 0))
        self.assertEqual(rgb.getpixel((400, 20)), (136, 136, 136))
        off = greyed()
        off.putpixel((700, 200), (130, 130, 130))
        with self.assertRaises(kit.InkError):
            kit.encode_png(off, "g16")
        with self.assertRaises(kit.InkError, msg="k4 PNG where g16 is expected"):
            kit.check_png(kit.encode_png(drawn()), (452, 444), "g16")
        with self.assertRaises(kit.InkError, msg="red isn't a grey"):
            kit.check_inks(drawn(), "g16")

    def test_g16_blob_id_is_sbp8_over_grey_rows(self):
        img = greyed(8, 2)
        want = hashlib.sha256(b"SBP8" + struct.pack("<HH", 8, 2) + img.convert("L").tobytes()).hexdigest()
        self.assertEqual(kit.blob_id(img, "g16"), want)
        # The hub's fixture: PackedImage::filled(P8, 1360, 360, 0x88).
        flat = Image.new("RGB", (1360, 360), kit.grey(8))
        want = hashlib.sha256(b"SBP8" + struct.pack("<HH", 1360, 360) + b"\x88" * (1360 * 360)).hexdigest()
        self.assertEqual(kit.blob_id(kit.encode_png(flat, "g16"), "g16"), want)

    def test_snap_g16(self):
        ramp = Image.linear_gradient("L").resize((256, 4)).convert("RGB")
        for dither in (False, True):
            snapped = kit.snap_g16(ramp, dither=dither)
            kit.check_inks(snapped, "g16")
        self.assertEqual(kit.snap_g16(Image.new("RGB", (1, 1), (130, 130, 130))).getpixel((0, 0)), kit.grey(8))
        with self.assertRaises(ValueError):
            kit.grey(16)

    def test_write_feed_in_g16(self):
        ctx = self.ctx(SLOWAPP_CONTRACT="5", SLOWAPP_FEEDS=SLEEP)
        doc = ctx.write_feed("sleep", [Card("home", greyed(), title="Today")])
        self.assertEqual(doc["surface"], "1360x360.g16")
        png = (Path(self.env["SLOWAPP_OUT"]) / "feeds" / "sleep" / "cards" / "home.png").read_bytes()
        kit.check_png(png, (1360, 360), "g16")


class Net(Env):
    def test_secret_honours_fixture_mode(self):
        self.assertEqual(self.ctx(SLOWAPP_MODE="fixture").secret("token"), "fixture-token")
        with self.assertRaises(kit.NeedsConfig):
            self.ctx().secret("token")
        self.assertIsNone(self.ctx().secret("token", optional=True))
        (self.tmp / "secrets" / "token").write_text("s3cret\n")
        self.assertEqual(self.ctx().secret("token"), "s3cret")

    def test_no_network_in_fixture_mode(self):
        with self.assertRaises(kit.ContractError):
            self.ctx(SLOWAPP_MODE="fixture").http_get("https://example.com/")

    def test_deadline_passed_is_transient(self):
        c = self.ctx(SLOWAPP_DEADLINE="2000-01-01T00:00:00-08:00")
        with self.assertRaises(kit.Transient):
            c.http_get("https://example.com/")

    def test_timeout_is_capped_to_the_deadline(self):
        from datetime import datetime, timedelta
        from unittest import mock
        seen = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout):
            seen.append(timeout)
            return Resp(b"{}")

        soon = (datetime.now().astimezone() + timedelta(seconds=30)).isoformat()
        later = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()
        with mock.patch("urllib.request.urlopen", urlopen):
            self.ctx(SLOWAPP_DEADLINE=soon).http_json("https://example.com/", timeout=60)
            self.ctx(SLOWAPP_DEADLINE=later).http_json("https://example.com/", timeout=60)
            self.ctx().http_json("https://example.com/", timeout=60)
        self.assertTrue(20 < seen[0] <= 30 - kit.net.DEADLINE_MARGIN_S, seen)   # 30 s left, minus the margin
        self.assertEqual(seen[1:], [60, 60])                                     # plenty left / no deadline

    def test_fetch_then_draw(self):
        c = self.ctx()
        self.assertEqual(c.fetch("a.json", lambda: {"t": 1}), {"t": 1})
        self.assertTrue((self.tmp / "data" / "snapshots" / "a.json").exists())
        c.exit_if_unchanged()                                 # no previous run
        kit.net.remember(c)
        self.assertTrue((self.tmp / "out" / "cache_key").exists())
        c2 = self.ctx()
        c2.fetch("a.json", lambda: {"t": 1})
        with self.assertRaises(kit.Unchanged):
            c2.exit_if_unchanged()
        c3 = self.ctx()
        c3.fetch("a.json", lambda: {"t": 2})
        c3.exit_if_unchanged()                                # changed: carries on
        # the live snapshot is the fixture
        kit.net.remember(c3)
        # contract 5: another device's run of the same job, on the same data, isn't unchanged
        dev = json.dumps({"id": "supernote", "profile": "supernote", "w": 1404, "h": 1872, "inks": "g16"})
        d = self.ctx(SLOWAPP_DEVICE=dev)
        d.fetch("a.json", lambda: {"t": 2})
        d.exit_if_unchanged()
        self.assertNotEqual(kit.net.snapshot_hash(d), kit.net.snapshot_hash(c3))
        f = self.ctx(SLOWAPP_MODE="fixture")
        self.assertEqual(f.fetch("a.json", lambda: self.fail("fn must not run in fixture mode")), {"t": 2})
        with self.assertRaises(kit.ContractError):
            f.fetch("missing.json", lambda: None)


class Jobs(Env):
    def setUp(self):
        super().setUp()
        import sample_app  # noqa: F401 - registers the jobs

    def test_exit_codes_and_metrics(self):
        for name, want in (("render", 0), ("flaky", 4), ("boom", 1), ("nope", 64)):
            code, _ = kit.execute(name, self.ctx())
            self.assertEqual(code, want, name)
            m = json.loads((self.tmp / "out" / ".metrics.json").read_text())
            self.assertEqual(m["exit"], want)
            self.assertGreater(m["ru_maxrss_kb"], 0)

    def test_ui_socket(self):
        os.environ.update(self.env)
        os.environ["SLOWAPP_JOB_LOCK"] = str(self.tmp / "lock")
        os.environ["SLOWAPP_ENTRYPOINT"] = json.dumps([sys.executable, str(HERE / "sample_app.py")])
        sock = str(self.tmp / "ui.sock")
        srv = kit.serve.make_server(sock)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertEqual(oct(os.stat(sock).st_mode & 0o777), "0o660")

            def call(method, path, body=None):
                conn = http.client.HTTPConnection("ui")
                conn.sock = socket.socket(socket.AF_UNIX)
                conn.sock.connect(sock)
                conn.request(method, path, body=body)
                r = conn.getresponse()
                out = r.status, json.loads(r.read())
                conn.close()
                return out

            self.assertEqual(call("GET", "/_sb/health")[1]["ok"], True)
            st, res = call("POST", "/_sb/jobs/render", json.dumps({"run_id": "r_9"}))
            self.assertEqual((st, res["exit"]), (200, 0))
            self.assertTrue((self.tmp / "out" / "r_9" / "feeds" / "left" / "deck.json").exists())
            self.assertTrue((self.tmp / "out" / "r_9" / ".metrics.json").exists())
            st, res = call("POST", "/_sb/jobs/flaky", "{}")
            self.assertEqual((res["exit"], res["message"]), (4, "upstream down"))
            self.assertEqual(call("POST", "/_sb/jobs/missing", "{}")[0], 404)
            self.assertEqual(call("GET", "/_sb/other")[0], 404)
            # slowbhub's warm dispatch: {"run_id", "out", "env"} (crates/slowbhub/src/supervisor/mod.rs)
            feeds = [{"feed": "right", "slot": "right", "w": 452, "h": 444, "inks": "k4", "bpp": 2, "key": "black"}]
            body = {"run_id": "r_hub", "out": "/out/r_hub".replace("/out", str(self.tmp / "out")),
                    "env": {"SLOWAPP_FEEDS": json.dumps(feeds), "SLOWAPP_FOR": "2026-10-06T10:00:00-07:00",
                            "SLOWAPP_DEADLINE": "2026-10-06T09:59:40-07:00", "SLOWAPP_REASON": "planner",
                            "SLOWAPP_NOW": "2026-10-06T09:58:19-07:00", "TZ": "America/Edmonton",
                            "SLOWAPP_STATE": "/elsewhere", "PATH": "/evil"}}
            st, res = call("POST", "/_sb/jobs/env", json.dumps(body))
            self.assertEqual((st, res["exit"]), (200, 0), res)
            seen = json.loads((self.tmp / "out" / "r_hub" / "env.json").read_text())
            self.assertEqual(seen, {"reason": "planner", "run_id": "r_hub", "for": "2026-10-06T10:00:00-07:00",
                                    "tz": "America/Edmonton", "deadline": "2026-10-06T09:59:40-07:00",
                                    "feeds": ["452x444.k4"], "data": str(self.tmp / "data")})
            # the same through top-level keys: feeds as a list, tz
            short = {"run_id": "r_top", "feeds": [dict(feeds[0], w=456, feed="middle")], "tz": "UTC",
                     "for": "2026-10-06T17:00:00+00:00", "reason": "planner"}
            st, res = call("POST", "/_sb/jobs/env", json.dumps(short))
            self.assertEqual((st, res["exit"]), (200, 0), res)
            seen = json.loads((self.tmp / "out" / "r_top" / "env.json").read_text())
            self.assertEqual((seen["feeds"], seen["tz"], seen["reason"]), (["456x444.k4"], "UTC", "planner"))
            # out must stay under the container's /out
            os.environ["SLOWAPP_OUT"] = "/out"
            self.assertEqual(call("POST", "/_sb/jobs/env", json.dumps(dict(body, out="/etc")))[0], 400)
            self.assertEqual(call("POST", "/_sb/jobs/env", json.dumps(dict(body, out="/out/../etc")))[0], 400)
            os.environ["SLOWAPP_OUT"] = str(self.tmp / "out")
            st, res = call("POST", "/_sb/events", '{"id":"e1","kind":"answer"}\n{"id":"e2","kind":"answer"}\n')
            self.assertEqual(res["exit"], 0)
            outs = [p for p in (self.tmp / "out").glob("*/events.json")]
            self.assertEqual([e["id"] for e in json.loads(outs[0].read_text())], ["e1", "e2"])
        finally:
            srv.shutdown()
            srv.server_close()
            for k in list(self.env) + ["SLOWAPP_JOB_LOCK", "SLOWAPP_ENTRYPOINT"]:
                os.environ.pop(k, None)


class UiLog(unittest.TestCase):
    def test_ring_stays_under_the_cap(self):
        with tempfile.TemporaryDirectory() as d:
            ring = kit.uilog.RingLog(os.path.join(d, "ui.log"), cap=4096)
            for i in range(2000):
                ring.write(f"line {i:05d} {'x' * 40}\n")
            text = Path(d, "ui.log").read_text()
            self.assertLessEqual(len(text), 4096)
            self.assertTrue(text.endswith("line 01999 " + "x" * 40 + "\n"))
            self.assertTrue(text.startswith("line "), "cut at a line boundary")

    def test_serve_logs_children_to_the_ring(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, SLOWAPP_UI_LOG=os.path.join(d, "ui.log"), SLOWAPP_UI_SOCK=os.path.join(d, "ui.sock"),
                       SLOWAPP_OUT=os.path.join(d, "out"), SLOWAPP_STATE=d, SLOWAPP_JOB_LOCK=os.path.join(d, "lock"),
                       SLOWAPP_ENTRYPOINT=json.dumps([sys.executable, str(HERE / "sample_app.py")]),
                       SLOWAPP_NOW="2026-10-06T09:00:00-07:00")
            import subprocess
            ui = subprocess.Popen([sys.executable, str(HERE / "sample_app.py"), "serve"], env=env,
                                  stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if os.path.exists(env["SLOWAPP_UI_SOCK"]):
                        break
                    threading.Event().wait(0.05)
                conn = http.client.HTTPConnection("ui")
                conn.sock = socket.socket(socket.AF_UNIX)
                conn.sock.connect(env["SLOWAPP_UI_SOCK"])
                conn.request("POST", "/_sb/jobs/env", body='{"run_id": "r_log"}')
                self.assertEqual(json.loads(conn.getresponse().read())["exit"], 0)
                conn.close()
                log = Path(d, "ui.log").read_text()
                self.assertIn("ui: listening on", log)
                self.assertIn("env job: hello from the child", log)
                self.assertIn('"POST /_sb/jobs/env HTTP/1.1" 200', log)
            finally:
                ui.kill()
                ui.wait()


class Blas(unittest.TestCase):
    def test_kit_pins_blas_threads_unless_set(self):
        import subprocess
        code = "import os, slowapp_kit; print(os.environ['OPENBLAS_NUM_THREADS'], os.environ['OMP_NUM_THREADS'])"
        env = {k: v for k, v in os.environ.items() if not k.endswith("_NUM_THREADS")}
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.split(), ["1", "1"])
        env["OPENBLAS_NUM_THREADS"] = "2"                      # an explicit setting wins (setdefault)
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.split(), ["2", "1"])


if __name__ == "__main__":
    unittest.main()
