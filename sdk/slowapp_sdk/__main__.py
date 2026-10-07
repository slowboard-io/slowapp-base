"""slowapp validate [DIR ...] | slowapp fixture [DIR] --image IMAGE [--repeat] [--out DIR]"""
import argparse
import sys

from . import validate


def fixture(a):
    from . import fixture        # needs Pillow; validate doesn't
    return fixture.cmd_test(a)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="slowapp", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check slowapp.toml against the schema and the cross-field rules")
    v.add_argument("dirs", nargs="*")
    v.set_defaults(fn=lambda a: validate.main(a.dirs))
    f = sub.add_parser("fixture", help="run every [[example]] in fixture mode and check /out")
    f.add_argument("dir", nargs="?", default=".")
    f.add_argument("--image", required=True, help="the app image to run, e.g. slowapp-example:dev")
    f.add_argument("--out", default="out/previews")
    f.add_argument("--repeat", action="store_true", help="run twice and require identical blob ids")
    f.set_defaults(fn=fixture)
    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
