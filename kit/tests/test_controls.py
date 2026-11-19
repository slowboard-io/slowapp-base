"""Card controls in the kit (slowboard docs/CONTROLS.md): written with the grant, every rule the hub
checks refused here first, and the screens an app's test can look at."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_kit import Env  # noqa: E402

import slowapp_kit as kit  # noqa: E402
from slowapp_kit import Card, Control, Controls, grey  # noqa: E402
from slowapp_kit import controls as ctl_mod  # noqa: E402

FEEDS = json.dumps([{"feed": "today", "w": 540, "h": 960, "inks": "g16", "bpp": 8}])
T = datetime(2026, 11, 18, 7, 30, tzinfo=timezone(timedelta(hours=-7)))
ROW = (0, 152, 480, 96)


def flat(w, h, level):
    return Image.new("RGB", (w, h), grey(level))


def toggle(cid="pills", rect=ROW, due=T):
    return Control(cid, "toggle", rect, {n: flat(rect[2], rect[3], lv) for n, lv in
                                         (("0", 15), ("1", 13), ("0f", 0), ("1f", 4))},
                   due=due, emit={"kind": "set", "data": {"task": cid}})


def tracker(**kw):
    a, b = toggle("a"), toggle("b", (0, 248, 480, 96), T + timedelta(hours=12))
    return Controls(items=[a, b], focus=["a", "b"], period="2026-11-18",
                    keys={"key1.tap": ("activate", "Done"), "key2.tap": ("next", "Next")}, **kw)


class ControlsOut(Env):
    def setUp(self):
        super().setUp()
        self.env.update(SLOWAPP_FEEDS=FEEDS, SLOWAPP_CONTRACT="5")
        (self.tmp / "slowapp.toml").write_text('[app]\nid="tracker"\ncontrols = true\n')

    def write(self, ctl):
        return self.ctx().write_feed("today", [Card("home", flat(540, 960, 15), "Today", controls=ctl)])

    def test_written_as_the_hub_reads_it(self):
        deck = self.write(tracker())
        c = deck["cards"][0]["controls"]
        self.assertEqual(c["focus"], {"order": ["a", "b"], "start": "first_open"})
        self.assertEqual(c["keys"]["key1.tap"], {"do": "activate", "label": "Done"})
        a = c["items"][0]
        self.assertEqual(a["due"], "2026-11-18T07:30:00-07:00")
        self.assertEqual(a["rect"], [0, 152, 480, 96])
        self.assertEqual(sorted(a["variants"]), ["0", "0f", "1", "1f"])
        png = (self.tmp / "out" / "feeds" / "today" / a["variants"]["0f"]).read_bytes()
        kit.check_png(png, (480, 96), "g16")
        self.assertEqual(a["variants"]["0f"], "controls/home/a/0f.png")

    def test_needs_the_grant(self):
        (self.tmp / "slowapp.toml").write_text('[app]\nid="tracker"\n')
        with self.assertRaisesRegex(kit.ContractError, "controls grant"):
            self.write(tracker())

    def test_refuses_what_the_hub_would(self):
        def no(f, why):
            c = tracker()
            f(c)
            with self.assertRaisesRegex(kit.ContractError, why):
                self.write(c)
        no(lambda c: c.items[0].variants.pop("1f"), "missing")
        no(lambda c: c.items[0].variants.update({"2": flat(480, 96, 0)}), "unexpected")
        no(lambda c: c.items[0].variants.update({"1": flat(400, 96, 0)}), "rect is 480x96")
        no(lambda c: setattr(c.items[0], "rect", (0, 152, 540, 96)), "overlaps the board's lane")
        no(lambda c: setattr(c.items[1], "rect", (0, 880, 480, 40)), "overlaps the board's strip")
        no(lambda c: setattr(c.items[0], "emit", None), "emit needs a kind")
        no(lambda c: setattr(c.items[0], "due", T.replace(tzinfo=None)), "no offset")
        no(lambda c: c.keys.update({"key1.tap": ("activate", "Tick this one off")}), "label")
        no(lambda c: c.keys.update({"key2.hold": ("next", "Next")}), "holds move between apps")
        no(lambda c: setattr(c, "focus", None), "nothing can have it")

    def test_shown_and_screens(self):
        c = tracker()
        names = lambda **kw: [n for _, n in ctl_mod.shown(c, **kw)]  # noqa: E731
        self.assertEqual(names(focus="a"), ["0f", "0"])
        self.assertEqual(names(values={"a": 1}, focus="b"), ["1", "0f"])
        self.assertEqual(names(), ["0", "0"])
        card = Card("home", flat(540, 960, 15), "Today", controls=c)
        shots = ctl_mod.screens(card)
        self.assertEqual(len(shots), 1 + 8)
        img = dict(shots)["a.0f"]
        self.assertEqual(img.getpixel((10, 160)), grey(0), "a's focused variant")
        self.assertEqual(img.getpixel((10, 260)), grey(15), "b as drawn")


if __name__ == "__main__":
    unittest.main()
