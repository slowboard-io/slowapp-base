"""Moon app unit tests: PYTHONPATH=kit:example python3 -m unittest discover -s example/tests"""
import unittest
from datetime import datetime, timedelta, timezone

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


if __name__ == "__main__":
    unittest.main()
