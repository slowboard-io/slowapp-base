"""slowapp validate [DIR ...] | slowapp fixture [DIR] --image IMAGE [--repeat] [--out DIR] |
slowapp catalog build|release|check …"""
import argparse
import sys

from . import validate


def fixture(a):
    from . import fixture        # needs Pillow; validate doesn't
    return fixture.cmd_test(a)


def _catalog(name, a):
    from . import catalog        # needs Pillow; validate doesn't
    return getattr(catalog, name)(a)


def add_catalog(sub):
    c = sub.add_parser("catalog", help="build, release or check an app's catalog bundle")
    cs = c.add_subparsers(dest="catalog_cmd", required=True)
    b = cs.add_parser("build", help="render every example at every size and write the bundle")
    b.add_argument("dir", nargs="?", default=".")
    b.add_argument("--image", required=True)
    b.add_argument("--out", default="out/catalog")
    b.add_argument("--slowd-image", help="the slowd-sim image, for full-panel pictures with real strips")
    b.add_argument("--slowd", help="a slowd binary instead of the image")
    b.set_defaults(fn=lambda a: _catalog("cmd_build", a))
    r = cs.add_parser("release", help="add the pushed image's sizes, the version and armv7 timings")
    r.add_argument("dir", nargs="?", default="out/catalog")
    r.add_argument("--app-dir", default=".")
    r.add_argument("--ref", required=True, help="e.g. ghcr.io/owner/slowapp-weather")
    r.add_argument("--digest", required=True)
    r.add_argument("--version", required=True)
    r.add_argument("--base", help="the base image (default: the Dockerfile's FROM)")
    r.add_argument("--armv7", help="summary.json of an armv7 fixture run")
    r.add_argument("--changelog", help="CHANGELOG.md; the section for --version goes in")
    r.set_defaults(fn=lambda a: _catalog("cmd_release", a))
    k = cs.add_parser("check", help="check a bundle: schema, file hashes, rules")
    k.add_argument("dir", nargs="?", default="out/catalog")
    k.set_defaults(fn=lambda a: _catalog("cmd_check", a))


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
    add_catalog(sub)
    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
