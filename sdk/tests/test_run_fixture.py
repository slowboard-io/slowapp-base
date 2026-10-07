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
                     "SLOWAPP_MODE=fixture", "SLOWAPP_CONTRACT=3", "img job render",
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


if __name__ == "__main__":
    unittest.main()
