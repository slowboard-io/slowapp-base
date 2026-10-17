"""Moon app unit tests: PYTHONPATH=kit:example python3 -m unittest discover -s example/tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from moon import phase


class Phase(unittest.TestCase):
    def test_known_moons(self):
        # 2026-10-26 04:12 UTC full moon; 2026-10-10 15:50 UTC new moon (published tables)
        self.assertGreater(phase.illumination(datetime(2026, 10, 26, 4, 12, tzinfo=timezone.utc)), 0.97)
        self.assertLess(phase.illumination(datetime(2026, 10, 10, 15, 50, tzinfo=timezone.utc)), 0.03)

    def test_next_phase_is_ahead_and_within_a_month(self):
        t = datetime(2026, 10, 7, 16, tzinfo=timezone.utc)
        for f in (0.0, 0.5):
            n = phase.next_phase(t, f)
            self.assertTrue(t <= n < t + timedelta(days=phase.SYNODIC_DAYS))


class PhasesJob(unittest.TestCase):
    """Contract 4: the UI's jobs.run("phases", {count}) gets the coming quarters in result.json."""

    def test_args_in_result_out(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for sub in ("in", "out", "data"):
                (d / sub).mkdir()
            (d / "in" / "args.json").write_text('{"count": 5}')
            here = Path(__file__).resolve().parents[1]
            env = dict(os.environ, SLOWAPP_CONTRACT="4", SLOWAPP_JOB="phases", SLOWAPP_MODE="live",
                       SLOWAPP_NOW="2026-10-07T09:00:00-07:00", TZ="America/Vancouver", SLOWAPP_FEEDS="[]",
                       SLOWAPP_IN=str(d / "in"), SLOWAPP_OUT=str(d / "out"), SLOWAPP_STATE=str(d / "data"),
                       SLOWAPP_MANIFEST=str(here / "slowapp.toml"),
                       # The child runs in example/: this process's (possibly relative) path, absolute.
                       PYTHONPATH=os.pathsep.join(os.path.abspath(p) for p in sys.path if p))
            r = subprocess.run([sys.executable, "-m", "moon", "job", "phases"], env=env, cwd=here,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            res = json.loads((d / "out" / "result.json").read_text())
        names = [p["name"] for p in res["phases"]]
        # 7 Oct 2026 is a waning crescent: new moon on the 10th, then the quarters in order.
        self.assertEqual(names, ["New moon", "First quarter", "Full moon", "Last quarter", "New moon"])
        # The published new moon is 10 Oct 08:50 local; the mean month is off by up to about a day.
        self.assertIn(res["phases"][0]["day"], ("Sat 10 Oct", "Sun 11 Oct"))
        ats = [p["at"] for p in res["phases"]]
        self.assertEqual(ats, sorted(ats))
        self.assertEqual(res["now"], "Waning crescent")


if __name__ == "__main__":
    unittest.main()
