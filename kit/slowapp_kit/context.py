"""The run context a job sees: identity, clock, mode, surfaces and paths (docs/SLOWBOARD.md §8.2, §8.3).

Every path can be moved with an environment variable so an app can run outside a container (tests,
the HostRunner in P2): SLOWAPP_STATE (/data), SLOWAPP_OUT (/out), SLOWAPP_IN (/in), SLOWAPP_SECRETS
(/run/secrets), SLOWAPP_CACHE (/cache), SLOWAPP_MANIFEST (/app/slowapp.toml).
"""
import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from .errors import ContractError
from .inks import INK_SETS, WHITE

SURFACE_RE = re.compile(r"^(\d{1,4})x(\d{1,4})\.([a-z0-9]+)$")


@dataclass(frozen=True)
class Surface:
    """One feed to draw and the glass it lands on: SLOWAPP_FEEDS entries (E4)."""
    feed: str
    w: int
    h: int
    inks: str = "k4"
    bpp: int = 2
    slot: str | None = None
    key: str | None = None

    @property
    def name(self):
        return f"{self.w}x{self.h}.{self.inks}"

    @classmethod
    def parse(cls, d):
        try:
            s = cls(feed=d["feed"], w=int(d["w"]), h=int(d["h"]), inks=d.get("inks", "k4"), bpp=int(d.get("bpp", 2)),
                    slot=d.get("slot"), key=d.get("key"))
        except (KeyError, TypeError, ValueError) as e:
            raise ContractError(f"bad SLOWAPP_FEEDS entry {d!r}: {e}")
        if s.inks not in INK_SETS or not (0 < s.w <= 4096 and 0 < s.h <= 4096):
            raise ContractError(f"unsupported surface {s.name}")
        return s

    @classmethod
    def from_name(cls, feed, name, **kw):
        m = SURFACE_RE.match(name)
        if not m:
            raise ContractError(f"surface {name!r} is not <w>x<h>.<inks>")
        return cls(feed=feed, w=int(m[1]), h=int(m[2]), inks=m[3], **kw)


def _time(v, tz):
    t = datetime.fromisoformat(v)
    return t if t.tzinfo else t.replace(tzinfo=tz)


def load_manifest(path=None):
    path = Path(path or os.environ.get("SLOWAPP_MANIFEST", "/app/slowapp.toml"))
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


@dataclass
class Context:
    app: str
    job: str
    run_id: str
    reason: str
    mode: str
    now: datetime
    for_: datetime
    deadline: datetime | None
    tz: ZoneInfo
    feeds: list
    data: Path
    out: Path
    inp: Path
    cache: Path
    secrets_dir: Path
    manifest: dict = field(default_factory=dict)
    _fetched: dict = field(default_factory=dict)

    @property
    def fixture(self):
        return self.mode == "fixture"

    @classmethod
    def from_env(cls, job=None, env=None, out=None):
        env = os.environ if env is None else env
        if env.get("SLOWAPP_CONTRACT", "3") != "3":
            raise ContractError(f"SLOWAPP_CONTRACT={env['SLOWAPP_CONTRACT']}: this kit speaks contract 3")
        tz = ZoneInfo(env.get("TZ") or "America/Vancouver")
        mode = env.get("SLOWAPP_MODE", "live")
        if mode not in ("live", "fixture"):
            raise ContractError(f"SLOWAPP_MODE={mode!r}")
        if mode == "fixture" and not env.get("SLOWAPP_NOW"):
            raise ContractError("fixture mode needs a fixed SLOWAPP_NOW")
        now = _time(env["SLOWAPP_NOW"], tz) if env.get("SLOWAPP_NOW") else datetime.now(tz)
        for_ = _time(env["SLOWAPP_FOR"], tz) if env.get("SLOWAPP_FOR") else now
        deadline = _time(env["SLOWAPP_DEADLINE"], tz) if env.get("SLOWAPP_DEADLINE") else None
        manifest = load_manifest(env.get("SLOWAPP_MANIFEST"))
        try:
            raw = json.loads(env.get("SLOWAPP_FEEDS") or "[]")
        except ValueError as e:
            raise ContractError(f"SLOWAPP_FEEDS is not JSON: {e}")
        if not isinstance(raw, list):
            raise ContractError("SLOWAPP_FEEDS must be a JSON list")
        return cls(
            app=env.get("SLOWAPP_APP") or manifest.get("app", {}).get("id", "app"),
            job=job or env.get("SLOWAPP_JOB", "render"),
            run_id=env.get("SLOWAPP_RUN_ID") or f"r_local_{now:%Y%m%dT%H%M%S}",
            reason=env.get("SLOWAPP_REASON", "fixture" if mode == "fixture" else "manual"),
            mode=mode, now=now, for_=for_, deadline=deadline, tz=tz,
            feeds=[Surface.parse(d) for d in raw],
            data=Path(env.get("SLOWAPP_STATE", "/data")),
            out=Path(out or env.get("SLOWAPP_OUT", "/out")),
            inp=Path(env.get("SLOWAPP_IN", "/in")),
            cache=Path(env.get("SLOWAPP_CACHE", "/cache")),
            secrets_dir=Path(env.get("SLOWAPP_SECRETS", "/run/secrets")),
            manifest=manifest,
        )

    # ------------------------------------------------------------ inputs

    def feed(self, name):
        """The surface for one feed. A feed the hub didn't ask for this run is None: skip it."""
        return next((s for s in self.feeds if s.feed == name), None)

    def _in_json(self, name, default):
        try:
            with open(self.inp / name) as f:
                return json.load(f)
        except FileNotFoundError:
            return default

    @property
    def settings(self):
        """/in/settings.json over the manifest's [settings] defaults."""
        out = {k: v["default"] for k, v in self.manifest.get("settings", {}).items()
               if isinstance(v, dict) and "default" in v}
        out.update(self._in_json("settings.json", {}))
        return out

    @property
    def layout(self):
        return self._in_json("layout.json", {})

    def events(self):
        """Events for an `event` job: /in/events.jsonl, or (warm UI) the /_sb/events body, which the
        kit hands the job child as SLOWAPP_EVENTS_FILE."""
        path = os.environ.get("SLOWAPP_EVENTS_FILE") or self.inp / "events.jsonl"
        try:
            text = Path(path).read_text()
        except FileNotFoundError:
            return []
        text = text.strip()
        if text.startswith("["):
            return json.loads(text)
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    # ------------------------------------------------------------ drawing

    def canvas(self, surface, fill=WHITE):
        return Image.new("RGB", (surface.w, surface.h), fill)

    def remaining(self):
        """Seconds until the deadline, or None if there is none."""
        if self.deadline is None:
            return None
        now = datetime.now(self.tz) if not self.fixture else self.now
        return (self.deadline - now) / timedelta(seconds=1)
