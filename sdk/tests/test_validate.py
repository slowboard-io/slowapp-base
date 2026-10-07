"""Manifest validator tests: python3 -m unittest discover -s sdk/tests"""
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from slowapp_sdk import validate as vp  # noqa: E402

SCHEMA = json.loads(vp.SCHEMA.read_text())

# The plan's example manifests (epaper-dashboard docs/SLOWBOARD.md §8.8), as contract 3
CALENDAR = '''
[app]
id = "calendar"
title = "Calendar"
contract = 3
image = "ghcr.io/mike-anderson/slowapp-calendar"
memory = "96m"
tmp = "16m"
timeout_s = 120
network = "egress"
secrets = ["digitalocean_token"]
optional_secrets = ["google_client"]
data = { max_mb = 32 }
cache = { tmpfs_mb = 0 }
exports = ["agenda"]
prompts = false

[settings]
tz_override = { type = "string", optional = true }
lookahead_days = { type = "number", default = 14, min = 1, max = 60 }

[ui]
idle_s = 120
start_timeout_s = 15

[events]
accept = []

[[job]]
name = "sync"
every = "15m"
jitter_s = 60

[[job]]
name = "ai"
daily = "05:00"

[[job]]
name = "render"
inputs = ["self:agenda"]
expected_s = 8

[[feed]]
name = "agenda"
size = "slot"

[[example]]
name = "busy-week"
fixture = "fixtures/busy-week"
now = "2026-10-06T08:00:00-07:00"
feeds = { agenda = "452x444.k4" }
'''

REMINDERS = '''
[app]
id = "reminders"
title = "Reminders"
contract = 3
image = "ghcr.io/mike-anderson/slowapp-reminders"
memory = "64m"
tmp = "8m"
timeout_s = 30
network = "none"
prompts = true
data = { max_mb = 4 }
[ui]
idle_s = 120
[events]
accept = ["answer"]
[[job]]
name = "render"
expected_s = 3
daily = "00:01"
[[job]]
name = "event"
[[feed]]
name = "prompts"
size = "slot"
'''


def check(text, app_dir=None):
    m = tomllib.loads(text)
    errs = vp.schema_errors(m, SCHEMA, SCHEMA)
    if errs:
        return errs, []
    return vp.rule_errors(m, app_dir)


class Plan(unittest.TestCase):
    def test_plan_examples_validate(self):
        with tempfile.TemporaryDirectory() as d:
            app = Path(d) / "calendar"
            (app / "fixtures" / "busy-week").mkdir(parents=True)
            errs, warns = check(CALENDAR, app)
            self.assertEqual(errs, [])
        errs, warns = check(REMINDERS)
        self.assertEqual(errs, [])
        self.assertIn("no [[example]]: CI can't render this app in fixture mode", warns)

    def test_example_app_validates(self):
        _, errs, _ = vp.validate(HERE.parents[1] / "example")
        self.assertEqual(errs, [])

    def test_schema_agrees_with_jsonschema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        jsonschema.Draft202012Validator.check_schema(SCHEMA)
        v = jsonschema.Draft202012Validator(SCHEMA)
        for text in (CALENDAR, REMINDERS, CALENDAR.replace('network = "egress"', 'network = "lan"'),
                     CALENDAR.replace('id = "calendar"', 'id = "Calendar"'), CALENDAR + "\nbogus = 1\n"):
            m = tomllib.loads(text)
            self.assertEqual(bool(list(v.iter_errors(m))), bool(vp.schema_errors(m, SCHEMA, SCHEMA)), text[-60:])


class Rules(unittest.TestCase):
    def bad(self, text, needle, app_dir=None):
        errs, _ = check(text, app_dir)
        self.assertTrue(any(needle in e for e in errs), f"{needle!r} not in {errs}")

    def test_structure(self):
        self.bad(CALENDAR.replace('network = "egress"', 'network = "lan"'), "not one of")
        self.bad(CALENDAR.replace('contract = 3', 'contract = 2'), "must be 3")
        self.bad(CALENDAR.replace('memory = "96m"', 'memory = "96MB"'), "doesn't match")
        self.bad(CALENDAR.replace('title = "Calendar"\n', ''), "missing 'title'")
        self.bad(CALENDAR + "\n[extra]\nx = 1\n", "unknown key 'extra'")
        self.bad(CALENDAR.replace('daily = "05:00"', 'daily = "25:00"'), "doesn't match")

    def test_cross_field(self):
        self.bad(CALENDAR.replace('name = "render"', 'name = "draw"').replace('job = "render"', ''), "named 'render'")
        self.bad(REMINDERS.replace("prompts = true", "prompts = false"), "needs prompts = true")
        self.bad(REMINDERS.replace('name = "event"', 'name = "evt"'), "needs a job named 'event'")
        self.bad(CALENDAR.replace('optional_secrets = ["google_client"]', 'optional_secrets = ["digitalocean_token"]'),
                 "both required and optional")
        self.bad(CALENDAR.replace('daily = "05:00"', 'daily = "05:00"\nevery = "1h"'), "exclusive")
        self.bad(CALENDAR.replace('every = "15m"', 'every = "2m"'), "under 5 minutes")
        self.bad(CALENDAR.replace("default = 14", "default = 99"), "outside min/max")
        self.bad(CALENDAR.replace('tmp = "16m"', 'tmp = "128m"'), "must fit inside memory")
        self.bad(CALENDAR.replace("agenda = \"452x444.k4\"", "nope = \"452x444.k4\""), "isn't declared")
        with tempfile.TemporaryDirectory() as d:
            self.bad(CALENDAR, "no directory fixtures/busy-week", Path(d) / "calendar")


if __name__ == "__main__":
    unittest.main()
