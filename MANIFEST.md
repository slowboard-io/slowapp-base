# App manifest (`slowapp.toml`), contract 4

A slowapp is an OCI image plus this manifest (the hub's design: epaper-dashboard
`docs/SLOWBOARD.md` §8; section numbers below refer to it). The manifest says what the app may
touch (its grants), which jobs it has, which feeds it draws and how CI renders it from a fixture.
The hub derives trust from where an app was installed from, never from the manifest (E10).

**Contract 4** adds app UIs: a single-file bundle the hub shows in a sandboxed frame (`[ui]
entry`), hub-stored JSON docs the UI edits (`[docs.<name>]`), and jobs a UI calls with arguments
(`[[job]] args`, `/in/args.json`, `/out/result.json`). A contract 3 manifest still validates and
still loads on a contract 4 hub; contract 4 keys need `contract = 4`. The JavaScript side is in
[`js/`](js/) (README: "App UIs").

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
| `contract` | `3` or `4` | The contract the app is written to (2 was 3 with `[pane]` and `EPAPER_*`). Its jobs get it as `SLOWAPP_CONTRACT`. |
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

`name` and `size`. `size = "slot"` means slot width × (480 − strip height) in the slot's inks, so
the hub passes the real surface in `SLOWAPP_FEEDS` (E4); `"WxH"` fixes it.

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
- Each example's fixture directory exists, its job and feeds are declared, and a fixed-size feed
  matches the example's surface. Warnings: a slot surface other than 452/456 × 444, a feed with no
  example, a required setting with no default.

## What the container sees

The full tables are docs/SLOWBOARD.md §8.2–§8.4; `slowapp_kit` reads all of it into `ctx`.

- **Command:** `job <name>` (attached, `--rm`) or `serve` (the UI on `/run/sb/ui.sock`). A warm
  UI gets jobs as `POST /_sb/jobs/<name>` with slowbhub's body `{"run_id", "out", "env"}`: the kit
  applies the per-run keys of `env` (`SLOWAPP_FEEDS`, `SLOWAPP_NOW`/`FOR`/`DEADLINE`, `SLOWAPP_REASON`,
  `SLOWAPP_MODE`, `SLOWAPP_RUN_ID`, `TZ`), ignores the rest, and writes to `out` (under `/out`).
- **Environment:** `SLOWAPP_CONTRACT` (the app's: `3` or `4`), `SLOWAPP_APP`, `SLOWAPP_JOB`, `SLOWAPP_RUN_ID`, `SLOWAPP_REASON`,
  `SLOWAPP_NOW`, `SLOWAPP_FOR`, `SLOWAPP_DEADLINE`, `TZ`, `SLOWAPP_MODE` (`live` | `fixture`),
  `SLOWAPP_FEEDS`, `SLOWAPP_STATE=/data`; BLAS threads are 1.
- **Mounts:** `/data` (rw; ro fixture copy), `/out`, `/in` (ro: `settings.json`, `layout.json`,
  `events.jsonl`; contract 4 adds `args.json` and `docs/<name>.json`), `/tmp` and `/cache` (tmpfs),
  `/run/secrets/<name>` (ro, live only), `/run/sb` (`ui.sock`, and `ui.log`: the UI's stderr and
  its job children's, kept as a 256 KB ring by the kit). The root filesystem is read-only.
- **Prompts** (the `prompts` grant): `/out/prompts.json`, each prompt's answers as
  `prompts/<id>/<binding>.png`, and optionally its question card `prompts/<id>/ask.png`
  (`"ask"` in prompts.json). With a question card the prompt takes its slot's whole body and the
  strip shows only the answers; without one the question goes in the strip.
- **Output:** `/out/feeds/<feed>/deck.json` and `cards/<id>.png` (exact surface size, 2- or 8-bit
  indexed, PLTE within the inks, no tRNS, ≤ 256 KB, ≤ 32 cards), plus optional `prompts.json`,
  `summary.json`, `cache_key`, `timing.json` and the kit's `.metrics.json`. Contract 4:
  `result.json` (back to the UI's `jobs.run`) and `docs/<name>.json`.
- **Exit codes:** 0 ingest · 3 unchanged · 4 transient · 5 needs config · 64 contract error ·
  137 killed. Anything else is a failure with backoff.

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
| `screens/<example>/<WxH>/<feed>-<card>.png` | Every card of every example at every size that works; for prompts, each question card (`kind` ask) and each answer's rest card (answer). 2-bit PNGs in the inks. |
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

