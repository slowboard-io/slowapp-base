"""Catalog bundle tests (no container engine needed): python3 -m unittest discover -s sdk/tests"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from slowapp_sdk import catalog, oci  # noqa: E402
from slowapp_kit.inks import encode_png  # noqa: E402

MANIFEST = """
[app]
id = "maps"
title = "Maps"
contract = 4
image = "ghcr.io/someone/slowapp-maps"
memory = "64m"
timeout_s = 30
network = "egress"
optional_secrets = ["key"]
prompts = true
blurb = "A map and a question."
ink = "red"
repo = "https://github.com/someone/slowapp-maps"

[[job]]
name = "render"

[[feed]]
name = "map"
size = "slot"

[[feed]]
name = "legend"
size = "452x444"

[[feed]]
name = "prompts"
size = "slot"

[[example]]
name = "noon"
caption = "Noon"
fixture = "fixtures/noon"
now = "2026-10-01T12:00:00-07:00"
feeds = { map = "456x444.k4", legend = "452x444.k4", prompts = "452x444.k4" }
"""

INKS = [(255, 255, 255), (0, 0, 0), (255, 0, 0), (255, 255, 0)]


class FakeRuns:
    """Stands in for fixture.run_example: writes /out for the surfaces asked. The map can't draw
    the whole panel (it writes nothing there); `flaky` makes every second run differ; nor can it
    in an example at a surface in `broken` ({(example, surface)}). `ids`: the cards' ids."""

    def __init__(self, flaky=False, broken=(), ids=("c0", "c1")):
        self.calls, self.flaky, self.broken, self.ids = [], flaky, set(broken), ids

    def __call__(self, app_dir, m, ex, image):
        self.calls.append(dict(ex["feeds"]))
        out = Path(tempfile.mkdtemp(prefix="sb-test-")) / "out"
        out.mkdir()
        shade = INKS[len(self.calls) % 2 + 1] if self.flaky else (0, 0, 0)
        for feed, surface in ex["feeds"].items():
            w, h = (int(v) for v in surface.split(".")[0].split("x"))
            if feed == "prompts":
                (out / "prompts" / "p1").mkdir(parents=True)
                (out / "prompts" / "p1" / "ask.png").write_bytes(encode_png(Image.new("RGB", (w, h), (255, 255, 0))))
                (out / "prompts" / "p1" / "done.png").write_bytes(encode_png(Image.new("RGB", (w, h), (255, 255, 255))))
                (out / "prompts.json").write_text(json.dumps({"surface": surface, "prompts": [{
                    "id": "p1", "question": "Water?", "from": "2026-10-01T12:00:00-07:00",
                    "until": "2026-10-01T13:00:00-07:00", "slot_hint": "middle", "ask": "prompts/p1/ask.png",
                    "bindings": {"own.tap": {"strip": "Done", "show": "prompts/p1/done.png"}}}]}))
                continue
            if feed == "map" and (w == 1360 or (ex["name"], surface) in self.broken):
                continue
            d = out / "feeds" / feed
            (d / "cards").mkdir(parents=True)
            cards = []
            for i, kind in enumerate(("home", "detail")):
                img = Image.new("RGB", (w, h), (255, 255, 255))
                img.paste(shade if i == 0 else (255, 0, 0), (10, 10, 60, 60))
                (d / "cards" / f"{self.ids[i]}.png").write_bytes(encode_png(img))
                cards.append({"id": self.ids[i], "title": f"{feed} {i}", "kind": kind})
            (d / "deck.json").write_text(json.dumps({"cards": cards, "valid_from": "2026-10-01T12:00:00-07:00",
                                                     "valid_until": "2026-10-01T13:00:00-07:00"}))
        (out / ".metrics.json").write_text(json.dumps({"memory_peak_kb": 1234}))
        return out, 0.5, ""


DUSK = """
[[example]]
name = "dusk"
fixture = "fixtures/noon"
now = "2026-10-01T19:00:00-07:00"
feeds = { map = "456x444.k4", legend = "452x444.k4" }
"""


def app_dir(root, extra=""):
    (root / "fixtures" / "noon").mkdir(parents=True)
    (root / "slowapp.toml").write_text(MANIFEST + extra)
    return root


def build(root, runs):
    a = SimpleNamespace(dir=str(root), image="img", out=str(root / "out"), slowd_image=None, slowd=None)
    with mock.patch.object(catalog, "run_example", runs), mock.patch.object(catalog, "ui_bundle", lambda m, i: None), \
            contextlib.redirect_stdout(io.StringIO()) as log:
        rc = catalog.cmd_build(a)
    return rc, log.getvalue()


class Build(unittest.TestCase):
    def setUp(self):
        self.root = app_dir(Path(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_every_size_rendered_twice_and_failures_listed(self):
        runs = FakeRuns()
        rc, log = build(self.root, runs)
        self.assertEqual(rc, 0, log)
        cat = json.loads((self.root / "out" / "catalog.json").read_text())
        # Its own surfaces, then each standard surface for the slot feeds, each twice.
        self.assertEqual(len(runs.calls), 8)
        self.assertEqual(runs.calls[2], {"map": "452x444.k4", "legend": "452x444.k4", "prompts": "452x444.k4"})
        self.assertEqual(runs.calls[4]["legend"], "452x444.k4", "a fixed feed keeps its size")
        feeds = {f["name"]: f for f in cat["feeds"]}
        m = feeds["map"]
        self.assertEqual(m["supported"], ["452x444.k4", "456x444.k4"])
        self.assertFalse(m["surfaces"]["1360x444.k4"]["ok"])
        self.assertIn("deck.json", m["surfaces"]["1360x444.k4"]["error"])
        self.assertEqual(feeds["legend"]["supported"], ["452x444.k4"])
        self.assertEqual(feeds["prompts"]["supported"], ["452x444.k4", "456x444.k4", "1360x444.k4"])
        self.assertEqual(m["screens"], {"home": 1, "detail": 1})
        self.assertEqual(feeds["prompts"]["screens"], {"ask": 1, "answer": 1})
        self.assertEqual(m["inks"], ["black", "white", "red"])
        answer = next(s for s in cat["screens"] if s["kind"] == "answer")
        self.assertEqual(answer["binding"], "own.tap")
        ex = cat["examples"][0]
        self.assertEqual([f["kind"] for f in ex["frames"]], ["home", "prompt"])
        self.assertFalse(ex["frames"][0]["strips"])
        self.assertEqual(ex["prompts"][0]["bindings"], {"own.tap": "Done"})
        self.assertEqual(ex["memory_peak_kb"], 1234)
        self.assertEqual(cat["app"]["author"], "someone")
        self.assertEqual(cat["grants"]["optional_secrets"], ["key"])
        self.assertEqual(catalog.check(self.root / "out"), [])
        # The prompt picture puts the question card on the hinted slot.
        img = Image.open(self.root / "out" / ex["frames"][1]["file"]).convert("RGB")
        self.assertEqual(img.getpixel((600, 200)), (255, 255, 0))

    def test_a_size_another_example_fails_at_drops_the_screens_there(self):
        root = app_dir(Path(tempfile.mkdtemp()), DUSK)
        self.addCleanup(shutil.rmtree, root, True)
        rc, log = build(root, FakeRuns(broken={("dusk", "452x444.k4")}))
        self.assertEqual(rc, 0, log)
        cat = json.loads((root / "out" / "catalog.json").read_text())
        m = next(f for f in cat["feeds"] if f["name"] == "map")
        self.assertEqual(m["supported"], ["456x444.k4"])
        self.assertIn("dusk:", m["surfaces"]["452x444.k4"]["error"])
        self.assertFalse([s for s in cat["screens"] if s["feed"] == "map" and s["surface"] == "452x444.k4"])
        self.assertFalse(list((root / "out" / "screens" / "noon" / "452x444.k4").glob("map/*.png")))
        self.assertEqual(catalog.check(root / "out"), [])

    def test_screen_names_dont_collide(self):
        rc, log = build(self.root, FakeRuns(ids=("x:1", "x_1")))
        self.assertEqual(rc, 0, log)
        cat = json.loads((self.root / "out" / "catalog.json").read_text())
        files = [s["file"] for s in cat["screens"]]
        self.assertEqual(len(files), len(set(files)))
        self.assertIn("screens/noon/456x444.k4/map/x_1~2.png", files)
        self.assertEqual(catalog.check(self.root / "out"), [])

    def test_prompts_json_of_an_example_without_the_prompts_feed_is_ignored(self):
        m = catalog.manifest(self.root)
        ex = dict(m["example"][0])
        runs = FakeRuns()
        surfaces = {"map": "456x444.k4", "legend": "452x444.k4"}

        def stray(app_dir, m, ex, image):   # the app writes prompts.json anyway
            return runs(app_dir, m, {**ex, "feeds": {**ex["feeds"], "prompts": "452x444.k4"}}, image)
        with mock.patch.object(catalog, "run_example", stray):
            res, _, _, prompts = catalog.render(self.root, m, ex, "img", surfaces)
        self.assertIsNone(prompts)
        self.assertEqual(set(res), {"map", "legend"})

    def test_a_ui_image_that_cant_be_created_is_a_failure_not_a_crash(self):
        m = {"ui": {"entry": "/ui/index.html"}}
        with mock.patch.object(catalog.subprocess, "run", lambda *a, **k: SimpleNamespace(
                returncode=1, stdout="", stderr="no such image")), mock.patch.object(catalog, "engine", lambda: "docker"):
            with self.assertRaisesRegex(catalog.Fail, "no such image"):
                catalog.ui_bundle(m, "img")

    def test_two_renders_that_differ_fail_the_build(self):
        rc, log = build(self.root, FakeRuns(flaky=True))
        self.assertEqual(rc, 1)
        self.assertIn("two renders differ", log)

    def test_the_full_panel_picture_comes_from_slowd_compose(self):
        seen = {}

        def fake_run(cmd, capture_output, timeout):
            work = Path(cmd[cmd.index("-v") + 1].split(":")[0])
            seen["spec"] = json.loads((work / "spec.json").read_text())
            seen["cmd"] = cmd
            Image.new("RGB", (1360, 480), (255, 0, 0)).save(work / "out.png")
            return SimpleNamespace(returncode=0, stderr=b"")
        comp = catalog.Composer(slowd_image="slowd-sim:test")
        res = {"map": {"deck": {"cards": [{"id": "a", "title": "Map"}, {"id": "b", "title": "Wind"}]},
                       "cards": {"a": (Image.new("RGB", (456, 444), (0, 0, 0)), "x")}}}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(catalog.subprocess, "run", fake_run), \
                mock.patch.object(catalog, "engine", lambda: "docker"):
            fr = catalog.frames(Path(d), {"name": "x"}, res, None, comp)
            self.assertEqual(Image.open(Path(d) / fr[0]["file"]).convert("RGB").getpixel((5, 5)), (255, 0, 0))
        self.assertTrue(fr[0]["strips"])
        self.assertEqual(seen["cmd"][-4:], ["slowd-sim:test", "compose", "spec.json", "out.png"])
        self.assertIn("--network", seen["cmd"])
        self.assertEqual(seen["spec"]["slots"]["middle"]["strip"],
                         {"kind": "armed", "key": "yellow", "next": "Wind", "n": 2, "cur": 0, "hold_home": False})
        self.assertEqual(seen["spec"]["slots"]["middle"]["body"], "middle.png")
        self.assertNotIn("layout", seen["spec"])

    def compose_specs(self, res, prompts):
        specs = []

        def fake_run(cmd, capture_output, timeout):
            work = Path(cmd[cmd.index("-v") + 1].split(":")[0])
            specs.append(json.loads((work / "spec.json").read_text()))
            Image.new("RGB", (1360, 480), (255, 255, 255)).save(work / "out.png")
            return SimpleNamespace(returncode=0, stderr=b"")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(catalog.subprocess, "run", fake_run), \
                mock.patch.object(catalog, "engine", lambda: "docker"), contextlib.redirect_stdout(io.StringIO()):
            fr = catalog.frames(Path(d), {"name": "x"}, res, prompts, catalog.Composer(slowd_image="s"))
        return fr, specs

    @staticmethod
    def feed(w):
        return {"deck": {"cards": [{"id": "a", "title": "A"}]}, "cards": {"a": (Image.new("RGB", (w, 444)), "x")}}

    @staticmethod
    def prompt(w, hint):
        return ({"deck": {"cards": [{"id": "p.ask", "title": "Q"}]}, "cards": {"p.ask": (Image.new("RGB", (w, 444)), "y")},
                 "prompts": True}, {"prompts": [{"id": "p", "question": "Q", "slot_hint": hint, "ask": "prompts/p/ask.png"}]})

    def test_a_whole_panel_feed_fills_the_full_panel_picture(self):
        fr, specs = self.compose_specs({"map": self.feed(1360)}, None)
        self.assertEqual(specs[0]["layout"]["slots"], [{"id": "full", "x0": 0, "x1": 1359, "key": "red"}])
        self.assertEqual(list(specs[0]["slots"]), ["full"])
        self.assertEqual(catalog.place({"map": self.feed(1360)}), {"map": "full"})
        img = catalog.frame({"map": self.feed(1360)})
        self.assertEqual(img.getpixel((700, 100)), (0, 0, 0))

    def test_a_prompt_card_too_wide_for_its_hinted_slot_goes_where_it_fits(self):
        pr, prompts = self.prompt(456, "left")
        fr, specs = self.compose_specs({"map": self.feed(452), "prompts": pr}, prompts)
        self.assertEqual(specs[1]["slots"]["middle"]["strip"]["kind"], "prompt")
        self.assertEqual(specs[1]["slots"]["left"]["strip"]["kind"], "single")
        # On a whole-panel layout no slot takes a third's card: the picture is skipped.
        pr, prompts = self.prompt(452, "middle")
        fr, specs = self.compose_specs({"map": self.feed(1360), "prompts": pr}, prompts)
        self.assertEqual([f["kind"] for f in fr], ["home"])

    def test_g16_feeds_are_not_the_boards(self):
        # Contract 5: a 1360-wide sleep strip isn't a whole-panel board card, and an example with
        # only feeds for other glass has no full-panel picture.
        sleep = dict(self.feed(1360), inks="g16")
        self.assertEqual(catalog.place({"sleep": sleep}), {})
        self.assertEqual(catalog.place({"sleep": sleep, "map": self.feed(452)}), {"map": "left"})
        fr, specs = self.compose_specs({"sleep": sleep}, None)
        self.assertEqual((fr, specs), ([], []))

    def test_g16_screens_are_grey_pngs(self):
        img = Image.new("RGB", (8, 2), (255, 255, 255))
        img.putpixel((0, 0), (136, 136, 136))
        with tempfile.TemporaryDirectory() as d:
            catalog.save_png(img, Path(d) / "s.png", "g16")
            data = (Path(d) / "s.png").read_bytes()
        self.assertEqual((data[24], data[25]), (8, 0))
        self.assertEqual(catalog.inks(img, "g16"), ["white", "grey"])
        with self.assertRaises(ValueError):          # a k4 screen has no greys
            catalog.inks(img)


class Check(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = app_dir(Path(tempfile.mkdtemp()))
        rc, log = build(cls.root, FakeRuns())
        assert rc == 0, log

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, True)

    def copy(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        shutil.copytree(self.root / "out", d / "b")
        return d / "b"

    def edit(self, b, fn):
        cat = json.loads((b / "catalog.json").read_text())
        fn(cat)
        (b / "catalog.json").write_text(json.dumps(cat))

    def test_a_good_bundle_passes(self):
        self.assertEqual(catalog.check(self.copy()), [])

    def test_schema_agrees_with_jsonschema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads(catalog.SCHEMA.read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        v = jsonschema.Draft202012Validator(schema)
        good = json.loads((self.root / "out" / "catalog.json").read_text())
        bad = json.loads(json.dumps(good))
        bad["screens"][0]["kind"] = "poster"
        for c in (good, bad):
            self.assertEqual(bool(list(v.iter_errors(c))),
                             bool(catalog.validate.schema_errors(c, schema, schema)))

    def test_a_tampered_screen_is_caught(self):
        b = self.copy()
        f = next(p for p in (b / "screens").rglob("c0.png") if p.parent.name == "map")
        with Image.open(f) as im:
            size = im.size
        Image.new("RGB", size, (0, 0, 0)).save(f)
        self.assertTrue(any("doesn't match its sha256" in e for e in catalog.check(b)))

    def test_rules(self):
        cases = [
            ("schema", lambda c: c["feeds"][0].update(supported=["big"]), "doesn't match"),
            ("hidden size", lambda c: c.update(screens=[s for s in c["screens"]
                                                       if not (s["feed"] == "map" and s["surface"] == "452x444.k4")]),
             "no screens of example noon at 452x444.k4"),
            ("unsupported screen", lambda c: c["feeds"][0].update(
                supported=["456x444.k4"], surfaces={"456x444.k4": {"ok": True}, "452x444.k4": {"ok": False}}),
             "isn't a supported surface"),
            ("escape", lambda c: c["screens"][0].update(file="screens/../../etc/x.png"), "outside the bundle"),
            ("other app", lambda c: c["app"].update(id="other"), "isn't the manifest's"),
            ("ui too big", lambda c: c.update(ui={"entry": "/ui/index.html", "bytes": 1, "gzip_bytes": 600 * 1024,
                                                  "sha256": "0" * 64}), "at most"),
        ]
        for what, fn, want in cases:
            b = self.copy()
            self.edit(b, fn)
            errs = catalog.check(b)
            self.assertTrue(any(want in e for e in errs), f"{what}: {errs}")


class Release(unittest.TestCase):
    def test_changelog_section(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "CHANGELOG.md"
            p.write_text("# Changelog\n\n## v0.3.0\n\n- A UI.\n- Docs.\n\n## [0.2.0] - 2026-10-01\n\n- Old.\n")
            self.assertEqual(catalog.changelog_for(p, "0.3.0"), "- A UI.\n- Docs.")
            self.assertEqual(catalog.changelog_for(p, "0.2.0"), "- Old.")
            self.assertIsNone(catalog.changelog_for(p, "0.3"))

    def test_base_from_dockerfile(self):
        pin = "ghcr.io/o/base:1.2.0@sha256:" + "a" * 64
        cases = [
            ("# x\nARG A=1\nfrom " + pin + " AS b\n", pin),
            ("ARG BASE=slowapp-python:dev\nFROM ${BASE}\n", "slowapp-python:dev"),
            # A UI stage first, --platform, quoted ARGs, and a final stage built on an earlier one.
            ('ARG REG="ghcr.io/o"\nARG TAG=1.2.0\nFROM --platform=$BUILDPLATFORM node:22 AS ui\n'
             "RUN npm ci\nFROM $REG/base:${TAG}@sha256:" + "a" * 64 + " AS App\nARG TAG=9\nFROM app\n", pin),
        ]
        for text, want in cases:
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "Dockerfile").write_text(text)
                self.assertEqual(catalog.base_of(Path(d) / "Dockerfile"), want, text)
        self.assertEqual(catalog.base_of(HERE.parent.parent / "example" / "Dockerfile"), "slowapp-python:dev")


APP = "sha256:" + "c" * 64


def layer(d, size):
    return {"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "digest": d, "size": size}


class Sizes(unittest.TestCase):
    def test_parse_ref(self):
        self.assertEqual(oci.parse_ref("ghcr.io/o/n:1.2@sha256:" + "b" * 64), ("ghcr.io", "o/n", "sha256:" + "b" * 64))
        self.assertEqual(oci.parse_ref("localhost:5000/n"), ("localhost:5000", "n", "latest"))
        with self.assertRaises(oci.RegistryError):
            oci.parse_ref("not a ref")

    def test_what_a_hub_with_the_base_adds(self):
        docs = {
            ("o/app", APP): {"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
                {"digest": "m1", "platform": {"os": "linux", "architecture": "arm", "variant": "v7"}},
                {"digest": "att", "platform": {"os": "unknown", "architecture": "unknown"}}]},
            ("o/app", "m1"): {"config": {"size": 10}, "layers": [layer("L1", 100), layer("L2", 50)]},
            ("o/base", "1.2.0"): {"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
                {"digest": "b1", "platform": {"os": "linux", "architecture": "arm", "variant": "v7"}}]},
            ("o/base", "b1"): {"config": {"size": 5}, "layers": [layer("L1", 100)]},
        }
        with mock.patch.object(oci.Registry, "manifest", lambda self, ref: docs[(self.repo, ref)]), \
                mock.patch.object(oci.Registry, "unpacked", lambda self, l: l["size"] * 3):
            s = oci.sizes("ghcr.io/o/app@" + APP, base="ghcr.io/o/base:1.2.0")
        self.assertEqual(s, {"linux/arm/v7": {"download": 160, "adds_download": 60, "layers": 2, "shared_layers": 1,
                                              "unpacked": 450, "adds_unpacked": 150}})


class Network(unittest.TestCase):
    def test_network_errors_are_registry_errors(self):
        import urllib.error
        reg = oci.Registry("ghcr.io", "o/app")
        for err in (urllib.error.URLError("no route"), TimeoutError("timed out")):
            with mock.patch.object(oci.urllib.request, "urlopen", side_effect=err):
                with self.assertRaisesRegex(oci.RegistryError, "ghcr.io/o/app/manifests/1"):
                    reg.manifest("1")
        with mock.patch.object(oci.urllib.request, "urlopen", side_effect=urllib.error.URLError("dns")):
            with self.assertRaisesRegex(oci.RegistryError, "token"):
                reg._authenticate('Bearer realm="https://ghcr.io/token",service="ghcr.io"')

    def test_a_layer_cut_off_mid_stream_is_a_registry_error(self):
        import http.client

        class Cut(io.BytesIO):
            status = 200

            def read(self, n=-1):
                raise http.client.IncompleteRead(b"")
        reg = oci.Registry("ghcr.io", "o/app")
        with mock.patch.object(reg, "open", lambda path, accept=None, headers=None: Cut()):
            with self.assertRaises(oci.RegistryError):
                reg.unpacked(layer("sha256:1", 100))

    def test_unpacked_size_from_the_gzip_trailer(self):
        import gzip
        data = gzip.compress(b"x" * 100000)
        reg = oci.Registry("ghcr.io", "o/app")

        def fake_open(path, accept=None, headers=None):
            r = io.BytesIO(data)
            if headers and "Range" in headers:
                a, b = (int(v) for v in headers["Range"][6:].split("-"))
                r, r.status = io.BytesIO(data[a:b + 1]), 206
            else:
                r.status = 200
            return r
        with mock.patch.object(reg, "open", fake_open):
            self.assertEqual(reg.unpacked(layer("sha256:1", len(data))), 100000)
        # A registry that ignores the range: the layer is streamed instead.
        with mock.patch.object(reg, "open", lambda path, accept=None, headers=None: _Body(data)):
            self.assertEqual(reg.unpacked(layer("sha256:1", len(data))), 100000)


class _Body(io.BytesIO):
    status = 200


class Grants(unittest.TestCase):
    def test_contract6_grants(self):
        import tomllib
        from test_validate import CALENDAR, CALENDAR6
        from slowapp_sdk import validate
        g = catalog.grants(tomllib.loads(CALENDAR6))
        self.assertEqual(g["network"], "egress", "a sync job reaches the network")
        self.assertEqual(g["secrets"], ["google"])
        self.assertEqual(g["optional_secrets"], ["icloud", "ai_key"])
        self.assertEqual(g["oauth"], {"google": {"provider": "google", "multiple": True, "scopes": [
            "https://www.googleapis.com/auth/calendar.readonly", "openid", "email"]}})
        schema = json.loads((Path(catalog.__file__).parent / "schema" / "catalog.schema.json").read_text())
        self.assertEqual(validate.schema_errors(g, schema["properties"]["grants"], schema), [])
        # No sync job with the network: none, whatever [app] network says.
        m = tomllib.loads(CALENDAR6.replace('network = "egress"\n', ''))
        self.assertEqual(catalog.grants(m)["network"], "none")
        # Before contract 6, as it was.
        g = catalog.grants(tomllib.loads(CALENDAR))
        self.assertEqual((g["network"], g["secrets"], g["optional_secrets"]), ("egress", ["digitalocean_token"], ["google_client"]))
        self.assertNotIn("oauth", g)


if __name__ == "__main__":
    unittest.main()
