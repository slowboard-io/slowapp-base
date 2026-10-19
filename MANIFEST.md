# App manifest (`slowapp.toml`), contract 5

A slowapp is an OCI image plus this manifest (the hub's design: epaper-dashboard
`docs/SLOWBOARD.md` §8; section numbers below refer to it). The manifest says what the app may
touch (its grants), which jobs it has, which feeds it draws and how CI renders it from a fixture.
The hub derives trust from where an app was installed from, never from the manifest (E10).

**Contract 4** adds app UIs: a single-file bundle the hub shows in a sandboxed frame (`[ui]
entry`), hub-stored JSON docs the UI edits (`[docs.<name>]`), and jobs a UI calls with arguments
(`[[job]] args`, `/in/args.json`, `/out/result.json`). A contract 3 manifest still validates and
still loads on a contract 4 hub; contract 4 keys need `contract = 4`. The JavaScript side is in
[`js/`](js/) (README: "App UIs").

**Contract 5** adds feeds for other glass, such as a Supernote's greyscale sleep screen.
- A `[[feed]]` may declare `inks = ["g16"]`, which is sixteen greys.
- A fixed-size feed is drawn for any device that asks for it.
- The hub runs `render` once per device. Each run's `SLOWAPP_FEEDS` holds only that device's feeds, and `SLOWAPP_DEVICE` (`ctx.device`) names the device. So draw what's asked for and nothing else.

- Structure: [`sdk/slowapp_sdk/schema/slowapp.schema.json`](sdk/slowapp_sdk/schema/slowapp.schema.json) (JSON Schema 2020-12).
- Rules a schema can't express: [`sdk/slowapp_sdk/validate.py`](sdk/slowapp_sdk/validate.py), listed below.
- Check an app: `python3 -m slowapp_sdk validate` in its repo (the SDK ships in every base image
  at `/opt/slowapp`); the app workflow runs it on every push.

Unknown keys are **errors** in the validator, so a typo can't silently drop a grant. The hub follows
the protocol rule and ignores unknown keys, so a newer manifest still loads on an older hub.

> The hub's `sb-proto` generates its own manifest schema (`proto/schema/slowapp.schema.json` in
> epaper-dashboard). The copy here must agree with it; bump `contract` in both together.

## Layout

One app per repo (`slowapp-<id>`):

```
slowapp.toml       this manifest
Dockerfile         FROM ghcr.io/…/slowapp-python[-sci]:X.Y.Z@sha256:…; the manifest goes to /app/slowapp.toml
<module>/          the app's code
fixtures/<name>/   /data for an [[example]] (read-only in fixture mode)
tests/             unit tests, run inside the base image
```

## `[app]`

| Key | Type | Meaning |
|---|---|---|
| `id` | string, `[a-z][a-z0-9-]{1,23}` | Names the container `sb-<id>`; the repo is `slowapp-<id>` by convention. |
| `title` | string, ≤ 40 | Shown on the hub's app card. |
| `contract` | `3`, `4` or `5` | The contract the app is written to (2 was 3 with `[pane]` and `EPAPER_*`). Its jobs get it as `SLOWAPP_CONTRACT`. |
| `image` | string | Registry path without tag; the hub's config pins `image@sha256:…`. |
| `memory` | size (`96m`, `1g`) | Hard limit: `--memory` = `--memory-swap`. Charged at admission (§7.4). |
| `tmp` | size | `--tmpfs /tmp:size=`. Counts against `memory`. |
| `timeout_s` | 1–3600 | The job is killed past this (exit 137, outcome `timeout`). |
| `network` | `none` \| `egress` | `egress` is `pasta --no-map-gw`: internet **and the LAN** (M14), never host loopback. |
| `secrets` | names | Required podman secrets at `/run/secrets/<name>`. Missing → exit 5. |
| `optional_secrets` | names | Mounted once set (from the CLI, or the app's UI with `secrets.set`). |
| `data` | `{ max_mb }` | `/data` bind mount. Over `max_mb` (checked with `du` after runs) pauses the app. |
| `cache` | `{ tmpfs_mb }` | `--tmpfs /cache`. Counts against `memory`. |
| `exports` | names | P4 transitional only (R3): files under `/export` other apps may import. |
| `imports` | `app:export` | P4 transitional only: mounted read-only at `/imports/<app>/`. |
| `prompts` | bool | The prompts grant: may write `/out/prompts.json`. Needs a feed named `prompts`. |
| `blurb` | string | Catalog: one line for the shelf, 1–100 characters. |
| `about` | string | Catalog: a short paragraph for the app's page, 1–800 characters. |
| `ink` | `black` \| `white` \| `yellow` \| `red` | Catalog: the ink of the app's disk. |
| `license` | string | Catalog: an SPDX expression (`MIT`, `Apache-2.0 OR MIT`). |
| `repo` | string | Catalog: the source repository, an `https://` URL. |

## `[settings]`

Each key is a setting the hub renders as a form field and writes to `/in/settings.json`
(`ctx.settings` merges the defaults in). Fields: `type` (`string`, `number`, `integer`, `boolean`,
`choice`), `label`, `help`, `optional`, `default`, `min`, `max`, `choices`.

## `[ui]` (optional)

| Key | Meaning |
|---|---|
| `entry` | Contract 4. The app's UI: one self-contained HTML file in the image (`/ui/index.html`), at most 2 MB, with its JS, CSS, fonts and images inlined (the frame can't fetch anything). The hub copies it out once per image and serves it in a sandboxed frame at `/apps/<id>`; opening it starts no container. Build it with `@slowboard/dev`'s Vite plugin. |
| `backend` | Contract 4. `true` also runs the image's `serve` for the UI's `backend.fetch` (the hub proxies it; slow on the board, so the exception). Contract 3's `[ui]` always means a backend. |
| `idle_s` | Backend only: stop after this long with no viewer and no job. |
| `start_timeout_s` | Backend only: how long `serve` may take to answer `/_sb/health`. |

## `[docs.<name>]` (contract 4)

The app's editable state as JSON documents the hub stores (in its database, so they're backed up
and need no container). The UI reads and writes them (`docs.get`, `docs.put` with the revision it
read; a stale one is refused with the current doc). Jobs get them at `/in/docs/<name>.json`
(`ctx.doc(name)`) and may write `/out/docs/<name>.json` (`ctx.write_doc(name, value)`), applied
only if the doc didn't change while the job ran (otherwise the job runs again). Big, binary or
private state stays in `/data`.

| Key | Meaning |
|---|---|
| `max_kb` | 1–1024, default 64: the largest the serialised doc may be. |
| `on_change` | Jobs to run after the UI writes it, 2 s after the last write. A job's write doesn't trigger them. |
| `writer` | `ui`, `job` or `both` (default): who may write it. |

## `[events]`

`accept = ["answer", ...]`: `emit` event kinds routed to this app. Needs a job named `event`.

## `[[job]]`

| Key | Meaning |
|---|---|
| `name` | `[a-z][a-z0-9_-]*`. `render` is the planner-driven output job; `event` receives events. |
| `every` | `15m`, `1h`: a wall-clock schedule (≥ 5 min), separate from the planner. |
| `daily` | `HH:MM` local. Exclusive with `every`. |
| `jitter_s` | Random delay added to a schedule. |
| `inputs` | `self:<export>` or `<app>:<export>`: the planner skips the job while their hash is unchanged. |
| `expected_s` | Duration hint until the hub has measured p90 (§7.5). |
| `args` | Contract 4: `{ name = "string" \| "number" \| "integer" \| "boolean" }`. What the UI may pass to `jobs.run`; the hub checks the types, refuses other names, and writes `/in/args.json` (`ctx.args`). All optional. The job's `/out/result.json` (`ctx.result(value)`, ≤ 256 KiB) goes back to the UI. |

Triggers are implied (E13): `on_demand` is always true and boot or fallback rules are hub policy.

## `[[feed]]`

| Key | Meaning |
|---|---|
| `name` | `[a-z][a-z0-9_-]*`. |
| `size` | `"slot"`: slot width × (480 − strip height) in the slot's inks, and the hub passes the real surface in `SLOWAPP_FEEDS` (E4). `"WxH"` fixes it; contract 5 draws a fixed-size feed for any device whose needs ask for it at that size. |
| `inks` | Contract 5. The ink sets the app draws the feed in: `k4` (the board's four inks, a 2-bit indexed PNG) or `g16` (sixteen greys 0, 17 … 255, an 8-bit grey PNG). Default `["k4"]`. A slot feed must include `k4`. |

```toml
[[feed]]          # today and five days for a Supernote's sleep screen
name = "sleep"
size = "1360x360"
inks = ["g16"]
```

The kit draws g16 with `grey(level)` colours (0 black … 15 white), or `snap_g16(img, dither=False)` over a free-form drawing. Text antialiasing lands between levels, and snapping fixes it.

## `[[example]]`

| Key | Meaning |
|---|---|
| `name` | Example name; previews are `<app>-<example>-<feed>-<card>.png`. |
| `fixture` | `fixtures/<dir>`, copied to `/data` read-only. |
| `now` | RFC 3339 with offset → `SLOWAPP_NOW`, `SLOWAPP_FOR`. |
| `feeds` | `{ feed = "452x444.k4" }`: which feeds to render, at which surface. |
| `job` | Default `render`. |
| `settings`, `tz`, `caption` | Optional. |

## `[ci]`

CI-only; the hub ignores it. `depends` (repo globs) is kept for compatibility; with one app per
repo every push renders the examples.

## Cross-field rules (`validate.py`)

- Job, feed and example names are unique.
- An app with feeds has a `render` job; `[events] accept` needs an `event` job.
- `prompts = true` if and only if there is a feed named `prompts`.
- A secret is either required or optional, not both.
- `every` and `daily` are exclusive; `jitter_s` needs one of them; `every` ≥ 5 min.
- `tmp` + `cache.tmpfs_mb` < `memory` (tmpfs is charged to the container).
- Setting defaults have the right type and sit within `min`/`max` and `choices`.
- Contract 4: `[ui]` has an `entry`, `backend = true` or both, and an `entry` has no `.` or `..`
  part; a doc's `on_change` jobs are declared; `[ui] entry`/`backend`, `[docs]` and job `args`
  need `contract = 4`. Warnings: backend-only `[ui]` keys next to a bundle-only UI, `[docs]`
  without a UI.
- Contract 5: `inks` other than `["k4"]` need `contract = 5`; a slot feed includes `k4`; the
  `prompts` feed is a k4 slot feed.
- Each example's fixture directory exists, its job and feeds are declared, a fixed-size feed
  matches the example's surface, and the surface's ink set is one of the feed's `inks`. Warnings: a slot surface other than 452/456 × 444, a feed with no
  example, a required setting with no default.

## What the container sees

The full tables are docs/SLOWBOARD.md §8.2–§8.4; `slowapp_kit` reads all of it into `ctx`.

- **Command:** `job <name>` (attached, `--rm`) or `serve` (the UI on `/run/sb/ui.sock`). A warm
  UI gets jobs as `POST /_sb/jobs/<name>` with slowbhub's body `{"run_id", "out", "env"}`: the kit
  applies the per-run keys of `env` (`SLOWAPP_FEEDS`, `SLOWAPP_NOW`/`FOR`/`DEADLINE`, `SLOWAPP_REASON`,
  `SLOWAPP_MODE`, `SLOWAPP_RUN_ID`, `TZ`), ignores the rest, and writes to `out` (under `/out`).
- **Environment:** `SLOWAPP_CONTRACT` (the app's: `3` to `5`), `SLOWAPP_APP`, `SLOWAPP_JOB`, `SLOWAPP_RUN_ID`, `SLOWAPP_REASON`,
  `SLOWAPP_NOW`, `SLOWAPP_FOR`, `SLOWAPP_DEADLINE`, `TZ`, `SLOWAPP_MODE` (`live` | `fixture`),
  `SLOWAPP_FEEDS`, `SLOWAPP_STATE=/data`; contract 5: `SLOWAPP_DEVICE`
  (`{"id","profile","w","h","inks"}`, unset in fixture mode); BLAS threads are 1.
- **Mounts:** `/data` (rw; ro fixture copy), `/out`, `/in` (ro: `settings.json`, `layout.json`,
  `events.jsonl`; contract 4 adds `args.json` and `docs/<name>.json`), `/tmp` and `/cache` (tmpfs),
  `/run/secrets/<name>` (ro, live only), `/run/sb` (`ui.sock`, and `ui.log`: the UI's stderr and
  its job children's, kept as a 256 KB ring by the kit). The root filesystem is read-only.
- **Prompts** (the `prompts` grant): `/out/prompts.json`, each prompt's answers as
  `prompts/<id>/<binding>.png`, and optionally its question card `prompts/<id>/ask.png`
  (`"ask"` in prompts.json). With a question card the prompt takes its slot's whole body and the
  strip shows only the answers; without one the question goes in the strip.
- **Output:** `/out/feeds/<feed>/deck.json` and `cards/<id>.png` (exact surface size; k4: 2- or
  8-bit indexed, PLTE within the inks; g16: 8-bit grey on the sixteen levels; no tRNS, ≤ 256 KB,
  ≤ 32 cards), plus optional `prompts.json`,
  `summary.json`, `cache_key`, `timing.json` and the kit's `.metrics.json`. Contract 4:
  `result.json` (back to the UI's `jobs.run`) and `docs/<name>.json`.
- **Exit codes:** 0 ingest · 3 unchanged · 4 transient · 5 needs config · 64 contract error ·
  137 killed. Anything else is a failure with backoff.

## Remote runs (the cloud hub)

The cloud hub runs each job on a throwaway Fly Machine made from the app's image, with no mounts:
`/in`, `/out` and `/data` travel as objects in Tigris behind presigned links. The base images
(1.4.0 and later) carry the wrapper that does this, `slowapp-remote`; app code doesn't change.

- **Command:** `slowapp-remote job <name>`, in place of `job <name>` (so `init.cmd` on the
  Machines API, keeping the image's `ENTRYPOINT`). A kit app takes that argv itself and runs
  `job <name>` as a child of its own entrypoint. An image with no `ENTRYPOINT` runs
  `/usr/local/bin/slowapp-remote`, which needs the app's command as `SLOWAPP_ENTRYPOINT` (a
  non-empty JSON list of strings, e.g. `["python3", "-m", "moon"]`); without either, or with a
  `SLOWAPP_ENTRYPOINT` that isn't such a list, it exits 64.
- **Environment:** everything a Podman run gets (`SLOWAPP_CONTRACT`, `SLOWAPP_APP`, `SLOWAPP_JOB`,
  `SLOWAPP_RUN_ID`, `SLOWAPP_REASON`, `SLOWAPP_NOW`/`FOR`/`DEADLINE`, `SLOWAPP_MODE`,
  `SLOWAPP_FEEDS`, `SLOWAPP_DEVICE`, `TZ`), plus:

  | Variable | | What |
  |---|---|---|
  | `SLOWAPP_REMOTE_IN` | required | Presigned GET of `in.tar`: what would be `/in`, relative names (`settings.json`, `docs/<name>.json`, …). |
  | `SLOWAPP_REMOTE_OUT` | required | Presigned PUT of `out.tar`: `/out` after the job. |
  | `SLOWAPP_REMOTE_LOG` | optional | Presigned PUT of the log: the run's stdout and stderr together, its last 64 KiB. |
  | `SLOWAPP_REMOTE_DATA_GET` | if saved | Presigned GET of the board's saved `/data` as `data.tar.gz`. A 404 still means none yet (start empty); any other error, a 403 included, fails the run (exit 4). |
  | `SLOWAPP_REMOTE_DATA_NEW` | if none saved | `1` when the hub knows the board has no saved `/data` yet, sent in place of `DATA_GET` (an S3 store without ListBucket answers a missing key with 403, so the hub decides, not the GET): `/data` starts empty. |
  | `SLOWAPP_REMOTE_DATA_PUT` | if `data` | Presigned PUT of the new `data.tar.gz`, used only when `/data` came through `DATA_GET` or `DATA_NEW=1` was set. A `DATA_PUT` with neither isn't used (the log says so, `data.status` is `"none"`), so an empty `/data` never replaces saved data. All three are left out when the app declares no `data`. |
  | `SLOWAPP_REMOTE_DATA_MAX_MB` | optional | The manifest's `data.max_mb` (read from `/app/slowapp.toml` if unset). `/data` over it isn't uploaded: the old one stays. |
  | `SLOWAPP_REMOTE_TIMEOUT_S` | optional | Kill the job child after this many seconds (exit 137) so the uploads still happen; set it a little under the machine's own stop. Unset, empty, 0 or less: no limit. Not a number: exit 64. |

  The job child gets none of the `SLOWAPP_REMOTE_*` variables. Its `SLOWAPP_IN`, `SLOWAPP_OUT`,
  `SLOWAPP_STATE` and `SLOWAPP_CACHE` point at fresh local directories (`/cache` starts empty and
  isn't kept). `SLOWAPP_DEADLINE` means what it does on a board, the time the job's fetches fit
  into, not a kill time.
- **Requests:** GETs follow redirects; PUTs send `Content-Length` (never chunked) and
  `Content-Type` `application/x-tar` (out), `application/gzip` (data) or `text/plain;
  charset=utf-8` (log), so sign only `host` or sign those. Each request has a 60 s timeout and is
  tried 3 times (2 s, then 4 s apart) on a network error (a broken or cut-short response
  included), 408, 429 or 5xx. Other 4xx, a link urllib can't use, a certificate that doesn't
  verify and a local file error aren't retried.
- **Archives:** an input archive is refused whole (nothing extracted) if any member has an
  absolute name or a `..`, is a device or fifo, or is a link that leaves the directory; then
  tarfile's `data` filter extracts it. `out.tar` and `data.tar.gz` hold directories and regular
  files under relative names; a symlink or special file the job made is left out and said in the
  log, and a file with several hard links goes in once per name, each a whole regular file.
- **Order:** fetch `in.tar` and the data, run the job, then always try to upload: `/data` (every
  run the job ran, whatever its exit, as a board keeps `/data`; never when the inputs failed, so a
  failed fetch can't wipe the saved data), then `out.tar` with the kit's `.metrics.json` and
  `.remote.json`, then the log, last, so it says how the uploads went.
- **Stopping:** on SIGTERM or SIGINT (the machine being stopped) the job child gets SIGTERM, then
  SIGKILL 3 s later if it's still running; the uploads then run as usual and the machine exits
  128 + the signal (143, 130), with `error` `"stopped by SIGTERM"` in `.remote.json`. A stop
  during the input fetches means the job doesn't run. Give the machine a kill timeout long enough
  for the uploads.
- **`.remote.json`** (in `out.tar`): `{"job", "run_id", "job_exit", "exit_code", "duration_ms",
  "started_at", "ended_at", "error", "data", "uploads_failed"}`. `job_exit` is the job's own code
  (`null` if it never ran: an input failed, the command was bad, it couldn't be started), `exit_code` what the machine exits with, times are UTC RFC 3339,
  `data` is `{"status": "none" | "saved" | "over_cap" | "failed", "loaded", "bytes", "max_mb"}`
  and `uploads_failed` lists `"data"` (and in the log, `"out"`).
- **Exit codes:** the job's own (0, 3, 4, 5, 64, 137, …), except **4** when an input fetch failed
  or an input archive was refused (the job didn't run), **4** when the job ran but `/data` or
  `out.tar` didn't upload (the log and `.remote.json` say which), **64** for a bad command
  (`SLOWAPP_ENTRYPOINT` included, or one that couldn't be started), a bad `SLOWAPP_REMOTE_TIMEOUT_S`
  or missing links, and **143** / **130** when the machine was stopped (SIGTERM / SIGINT). A failed log upload changes nothing: it shows in the machine's own log.

## Fixture mode

`SLOWAPP_MODE=fixture`, `--network none`, no secrets (`ctx.secret()` returns `fixture-<name>`), the
example's fixture as a read-only `/data` and a fixed `SLOWAPP_NOW`. The same fixture must give the
same pixels: `slowapp fixture` prints each card's blob id, so a change in pixels shows up
as a changed id. The runner uses a CI subset of §8.4: the same isolation flags (read-only root,
`--network none`, memory = swap, `--pids-limit 64`, `--oom-score-adj 500`, caps dropped,
no-new-privileges, the mounts), without the hub's `--cidfile`/`--conmon-pidfile` bookkeeping and
without `--log-driver none`, because the runner reports the app's stderr. Fixtures follow the fetch-then-draw convention: a live run's `/data/snapshots/`
can be copied into `fixtures/<name>/` as it is.

Run one locally (Docker or Podman; set `SLOWAPP_PLATFORM=linux/arm/v7` to emulate the board):

```sh
docker build -t slowapp-moon:dev .
python3 -m slowapp_sdk fixture --image slowapp-moon:dev --repeat     # PYTHONPATH: the SDK, see README
```

## Catalog bundle

An app's catalog page (on slowboard.io and in a hub's Apps pages) is computed from the image and
from renders of the app's own examples; only the words come from `[app]`. `app.yml` builds the
bundle on every run (artifact `catalog`) and finishes it on a release:

```sh
python3 -m slowapp_sdk catalog build --image slowapp-moon:dev --slowd-image ghcr.io/mike-anderson/slowd-sim:0.1.0
python3 -m slowapp_sdk catalog check out/catalog
```

`build` runs every `[[example]]` twice (the renders must match pixel for pixel) at its own
surfaces, then again with every `slot` feed at each standard surface: `452x444.k4`, `456x444.k4`
(the Lyra's thirds) and `1360x444.k4` (the whole panel as one slot). It writes `out/catalog/`:

| File | What |
|---|---|
| `catalog.json` | The app's words, the manifest and its sha256, the grants, per feed the surfaces it supports (each failure listed with its reason, never hidden), the inks it uses and its screens per example by kind, per example its timing and peak memory, and every screen with its sha256. Schema: `sdk/slowapp_sdk/schema/catalog.schema.json`. |
| `screens/<example>/<surface>/<feed>/<card>.png` | Every card of every example at every size that works (a size another example fails at is unsupported, and shows no screens); for prompts, each question card (`kind` ask) and each answer's rest card (answer). 2-bit PNGs in the inks. A card id's characters outside `A-Za-z0-9._-` become `_`, and a name that's already taken gets `~2`, `~3`, …. |
| `screens/<example>/panel-home.png`, `panel-prompt.png` | The whole panel: the home cards in their slots under the strips slowd draws (armed key, next card, deck dots), and the first prompt on its slot. Drawn by `slowd compose` from the slowd-sim image; without it (`--slowd-image` unset or not pullable) the strips are blank and `strips` is false. |

`release` (in `app.yml` after the push) adds the image's size per platform, read from the registry
(download, unpacked, and what it adds on a hub that already has the base the Dockerfile pins), the
version and its `## X.Y.Z` section of `CHANGELOG.md` if there is one, and the examples timed on
armv7 under QEMU. The release gets `catalog-<id>-<version>.json` and `.tar.gz`, and the same
files are attached to the image as an OCI artifact (`application/vnd.slowboard.catalog.v1`) that
refers to its digest:

```sh
oras discover --artifact-type application/vnd.slowboard.catalog.v1 ghcr.io/<owner>/<app>@sha256:…
```

`check` is the registry's first step on a submission: the schema, every file against its sha256,
screens only at supported sizes, and every supported size shown for every example (exhaustive).

