"""Fixture runner tests (no container engine needed): python3 -m unittest discover -s sdk/tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from slowapp_sdk import fixture as rf  # noqa: E402
from slowapp_kit.inks import encode_png  # noqa: E402

EXAMPLE = {"name": "x", "fixture": "fixtures/x", "now": "2026-10-01T13:15:00-07:00",
           "feeds": {"left": "452x444.k4", "middle": "456x444.k4"}}


def write_out(root, cards=None, size=(452, 444), kinds=("home", "detail")):
    for feed, w in (("left", 452), ("middle", 456)):
        d = root / "feeds" / feed
        (d / "cards").mkdir(parents=True)
        deck = {"cards": [], "valid_from": "2026-10-01T13:15:00-07:00", "valid_until": "2026-10-01T14:00:00-07:00"}
        for i, kind in enumerate(kinds):
            cid = f"c{i}"
            (d / "cards" / f"{cid}.png").write_bytes(encode_png(Image.new("RGB", (w if size == (452, 444) else size[0], size[1]), (255, 255, 255))))
            deck["cards"].append({"id": cid, "title": f"T{i}", "peek": "", "kind": kind})
        (d / "deck.json").write_text(json.dumps(deck))


class RunArgs(unittest.TestCase):
    def test_fixture_flags(self):
        m = rf.manifest(HERE.parents[1] / "example")
        args = rf.run_args(m, m["example"][0], "img", "/d", "/o", "/i", "r_1", "sb-example-1", "/r")
        s = " ".join(args)
        for want in ("--read-only", "--network none", "--memory 48m", "--memory-swap 48m", "--pids-limit 64",
                     "--cap-drop all", "no-new-privileges", "/d:/data:ro", "/o:/out", "/i:/in:ro",
                     "SLOWAPP_MODE=fixture", "SLOWAPP_CONTRACT=4", "img job render",
                     "--oom-score-adj 500", "/r:/run/sb", "sb.hub=ci"):
            self.assertIn(want, s)
        self.assertNotIn("/run/secrets", s)
        feeds = json.loads(next(a for a in args if a.startswith("SLOWAPP_FEEDS="))[len("SLOWAPP_FEEDS="):])
        self.assertEqual([(f["feed"], f["w"], f["key"]) for f in feeds],
                         [("phase", 456, None)])


class CheckOut(unittest.TestCase):
    def test_good_output(self):
        with tempfile.TemporaryDirectory() as d:
            write_out(Path(d))
            res = rf.check_out(Path(d), EXAMPLE)
            self.assertEqual(sorted(res), ["left", "middle"])
            self.assertEqual(len(res["left"]["cards"]["c0"][1]), 64)
            self.assertEqual(rf.frame(res).size, (1360, 480))

    def test_bad_output(self):
        for kw in (dict(size=(400, 444)), dict(kinds=("detail",)), dict(kinds=("home", "home"))):
            with tempfile.TemporaryDirectory() as d:
                write_out(Path(d), **kw)
                with self.assertRaises(rf.Fail):
                    rf.check_out(Path(d), EXAMPLE)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(rf.Fail):
                rf.check_out(Path(d), EXAMPLE)


class Prompts(unittest.TestCase):
    def write(self, root, size=(452, 444), surface="452x444.k4", until="2026-10-06T18:00:00-07:00"):
        (root / "prompts" / "p1").mkdir(parents=True)
        bindings = {}
        for name in ("own.tap", "spare.tap"):
            (root / "prompts" / "p1" / f"{name}.png").write_bytes(encode_png(Image.new("RGB", size, (255, 255, 255))))
            bindings[name] = {"show": f"prompts/p1/{name}.png", "strip": "ok", "emit": {"kind": "answer", "data": {}}}
        (root / "prompts.json").write_text(json.dumps({"surface": surface, "prompts": [
            {"id": "p1", "question": "Water the plants?", "from": "2026-10-06T09:00:00-07:00", "until": until,
             "bindings": bindings}]}))

    EX = {"name": "x", "fixture": "fixtures/x", "now": "2026-10-06T10:00:00-07:00", "feeds": {"prompts": "452x444.k4"}}

    def test_preview_names_are_artifact_safe(self):
        self.assertEqual(rf.safe_file("r-due-prompts-a1@2026-10-06T09:00.own.tap.png"),
                         "r-due-prompts-a1_2026-10-06T09_00.own.tap.png")

    def test_good(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(Path(d))
            res = rf.check_out(Path(d), self.EX)
            self.assertEqual(sorted(res["prompts"]["cards"]), ["p1.own.tap", "p1.spare.tap"])
            self.assertEqual(rf.frame(res).size, (1360, 480))

    def test_question_card(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.write(root)
            doc = json.loads((root / "prompts.json").read_text())
            doc["prompts"][0]["ask"] = "prompts/p1/ask.png"
            (root / "prompts.json").write_text(json.dumps(doc))
            with self.assertRaises(rf.Fail):                    # declared but not written
                rf.check_out(root, self.EX)
            (root / "prompts" / "p1" / "ask.png").write_bytes(encode_png(Image.new("RGB", (452, 444), (255, 255, 255))))
            self.assertIn("p1.ask", rf.check_out(root, self.EX)["prompts"]["cards"])

    def test_bad(self):
        for kw in (dict(size=(400, 444)), dict(surface="456x444.k4"), dict(until="2026-10-06T08:00:00-07:00")):
            with tempfile.TemporaryDirectory() as d:
                self.write(Path(d), **kw)
                with self.assertRaises(rf.Fail):
                    rf.check_out(Path(d), self.EX)


if __name__ == "__main__":
    unittest.main()
