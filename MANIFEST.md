# App manifest (`slowapp.toml`), contract 6

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

**Contract 6** splits fetching from drawing, so secrets reach only the runs that need them.
- A **sync** job (`[[job]] kind = "sync"`) runs once per install (a household's copy of the app), with the network and only the secrets it names (`[[job]] secrets`). It writes artifacts, `/out/artifacts/<name>/`.
- A **render** job (every other job, `render` included) runs once per device with no network and no secrets. It draws from the sync job's artifacts at `/in/artifacts/<name>/`.
- Secrets are declared as `[secrets.<name>]`: a value the household types in, or an OAuth sign-in (`kind = "oauth"`, `[auth.<provider>]`) the hub runs and hands the sync job as a short-lived access token (`token(name)` in the kit).
- A contract 3 to 5 manifest still loads unchanged: its app-level `secrets` read as value secrets on every job, and its jobs keep the app's `network`.

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
| `contract` | `3` to `6` | The contract the app is written to (2 was 3 with `[pane]` and `EPAPER_*`). Its jobs get it as `SLOWAPP_CONTRACT`. |
| `image` | string | Registry path without tag; the hub's config pins `image@sha256:…`. |
| `memory` | size (`96m`, `1g`) | Hard limit: `--memory` = `--memory-swap`. Charged at admission (§7.4). |
| `tmp` | size | `--tmpfs /tmp:size=`. Counts against `memory`. |
| `timeout_s` | 1–3600 | The job is killed past this (exit 137, outcome `timeout`). |
| `network` | `none` \| `egress` | `egress` is `pasta --no-map-gw`: internet **and the LAN** (M14), never host loopback. Contract 6: the default for sync jobs only; render jobs never have the network. |
| `secrets` | names | Contracts 3 to 5: required secrets at `/run/secrets/<name>`, on every job. Missing → exit 5. Contract 6 uses `[secrets.<name>]` instead (an error here). |
| `optional_secrets` | names | Contracts 3 to 5: mounted once set (from the CLI, or the app's UI with `secrets.set`). |
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

## `[secrets.<name>]` (contract 6)

Each secret the app takes. The hub keeps it sealed per install and hands it only to the sync jobs
that list it in `[[job]] secrets`, as a file and never an environment variable. The app's UI sets,
connects and clears secrets through the bridge (`secrets.*`, `<sb-secret-field>`, `<sb-connect>`)
and only ever sees whether one is set, never its value.

| Key | Meaning |
|---|---|
| `kind` | `value` (default): something the household types in, such as an API key. `/run/secrets/<name>`, read with `secret(name)`. `oauth`: a sign-in the hub runs with `[auth.<provider>]`; the run gets a fresh access token, `/run/secrets/<name>.json`, read with `token(name)`. |
| `label` | What the hub's page and the UI elements call it (≤ 60). |
| `help` | A line under the field (≤ 400). |
| `optional` | `true`: a run without it goes ahead. A required secret that isn't set holds the job (exit 5, `needs_config`). |
| `auth` | `oauth` only: the `[auth.<provider>]` to sign in with. |
| `multiple` | `oauth` only: several accounts under one secret (a household's Google accounts). Each is `/run/secrets/<name>/<account>.json`, and `token(name)` gives a list. |

```toml
[secrets.google]
kind = "oauth"
auth = "google"
multiple = true
label = "Google Calendar"

[secrets.ai_key]                 # an OpenAI-compatible key; its base URL is a setting
label = "AI key"
optional = true
```

## `[auth.<provider>]` (contract 6)

Where an `oauth` secret signs in and what it asks for. The client (its id and secret) is the hub's
own config, never the manifest's: which apps may use which client is the hub's decision (E10). The
hub runs the authorization-code flow at top level with one redirect URI, keeps the refresh token
sealed and writes a one-hour access token into each sync run that names the secret.

| Key | Meaning |
|---|---|
| `authorize_url`, `token_url` | `https://` URLs. Required. |
| `revoke_url` | `https://`: called on Disconnect. |
| `scopes` | What to ask for. The hub refuses a grant that doesn't cover them. |
| `pkce` | `true` (S256) unless the provider can't. |
| `params` | Extra authorize parameters, strings (`access_type = "offline"`, `prompt = "consent"`). |
| `label` | The provider's name on the Connect button (default: the secret's label). |

```toml
[auth.google]
authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
token_url = "https://oauth2.googleapis.com/token"
revoke_url = "https://oauth2.googleapis.com/revoke"
scopes = ["https://www.googleapis.com/auth/calendar.readonly", "openid", "email"]
params = { access_type = "offline", prompt = "consent" }
```

## `[artifacts.<name>]` (contract 6)

What sync jobs hand render: each a directory of files the sync job writes at
`/out/artifacts/<name>/` and render reads at `/in/artifacts/<name>/` (read only). The hub keeps the
latest per install, sealed, and runs render again when one's hash changes, for the render jobs that
list it as `inputs = ["self:<name>"]`. A sync run that exits 0 replaces each artifact it wrote
whole; one it didn't write stays as it was. Within an app this replaces R3's `exports` and
`imports`.

| Key | Meaning |
|---|---|
| `max_kb` | 1–65536, required: the most the artifact's files may add up to. Over it, the run is a contract error (64) and the old artifact stays. |

## `[events]`

`accept = ["answer", ...]`: `emit` event kinds routed to this app. Needs a job named `event`.

## `[[job]]`

| Key | Meaning |
|---|---|
| `name` | `[a-z][a-z0-9_-]*`. `render` is the planner-driven output job; `event` receives events. |
| `kind` | Contract 6: `render` (default) or `sync`. A sync job runs once per install with its `network` and `secrets`, and writes artifacts; a render job runs per device with no network and no secrets. The job named `render` is always render. |
| `network` | Contract 6, sync jobs only: `none` or `egress` (default: `[app] network`). |
| `secrets` | Contract 6, sync jobs only: the `[secrets]` this job gets. Nothing else reaches it. |
| `every` | `15m`, `1h`: a wall-clock schedule (≥ 5 min), separate from the planner. For a sync job, the default cadence: a household may slow it down, not below `min_every`. |
| `min_every` | Contract 6, sync jobs with `every`: the fastest a household may set it (≥ 5 min). "Update now" runs are capped separately by the hub. The two set the hub's daily budget for handing out the job's secrets. |
| `daily` | `HH:MM` local. Exclusive with `every`. |
| `jitter_s` | Random delay added to a schedule. |
| `inputs` | `self:<export>` or `<app>:<export>`: the planner skips the job while their hash is unchanged. Contract 6: `self:<artifact>` for an artifact a sync job writes. |
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
- Contract 6: `[secrets]`, `[auth]`, `[artifacts]` and a job's `kind`, `network`, `secrets` and
  `min_every` need `contract = 6`, and a contract 6 app has no app-level `secrets` or
  `optional_secrets`. A render job (any job without `kind = "sync"`) declares no `secrets`, no
  `network` and no `min_every`; the job named `render` isn't a sync job. A job's secrets are
  declared in `[secrets]`; an `oauth` secret names a declared `[auth]` provider, and `auth` and
  `multiple` are for `oauth` only. `min_every` needs `every` and is between 5 minutes and `every`.
  `[artifacts]` need a sync job. Warnings: a secret no job lists, a provider no secret uses, an
  artifact no render job has as an input.
- Each example's fixture directory exists, its job and feeds are declared, a fixed-size feed
  matches the example's surface, and the surface's ink set is one of the feed's `inks`. Warnings: a slot surface other than 452/456 × 444, a feed with no
  example, a required setting with no default.

## What the container sees

The full tables are docs/SLOWBOARD.md §8.2–§8.4; `slowapp_kit` reads all of it into `ctx`.

- **Command:** `job <name>` (attached, `--rm`) or `serve` (the UI on `/run/sb/ui.sock`). A warm
  UI gets jobs as `POST /_sb/jobs/<name>` with slowbhub's body `{"run_id", "out", "env"}`: the kit
  applies the per-run keys of `env` (`SLOWAPP_FEEDS`, `SLOWAPP_NOW`/`FOR`/`DEADLINE`, `SLOWAPP_REASON`,
  `SLOWAPP_MODE`, `SLOWAPP_RUN_ID`, `TZ`), ignores the rest, and writes to `out` (under `/out`).
- **Environment:** `SLOWAPP_CONTRACT` (the app's: `3` to `6`), `SLOWAPP_APP`, `SLOWAPP_JOB`, `SLOWAPP_RUN_ID`, `SLOWAPP_REASON`,
  `SLOWAPP_NOW`, `SLOWAPP_FOR`, `SLOWAPP_DEADLINE`, `TZ`, `SLOWAPP_MODE` (`live` | `fixture`),
  `SLOWAPP_FEEDS`, `SLOWAPP_STATE=/data`; contract 5: `SLOWAPP_DEVICE`
  (`{"id","profile","w","h","inks"}`, unset in fixture mode); BLAS threads are 1.
- **Mounts:** `/data` (rw; ro fixture copy), `/out`, `/in` (ro: `settings.json`, `layout.json`,
  `events.jsonl`; contract 4 adds `args.json` and `docs/<name>.json`; contract 6 adds, for render,
  `artifacts/<name>/`), `/tmp` and `/cache` (tmpfs), `/run/secrets` (ro, live only), `/run/sb`
  (`ui.sock`, and `ui.log`: the UI's stderr and its job children's, kept as a 256 KB ring by the
  kit). The root filesystem is read-only.
- **Secrets** (`/run/secrets`): a value secret is the file `<name>` (`secret(name)`). An oauth
  secret (contract 6) is `<name>.json`, `{"access_token", "expires_at", "scopes"}` with
  `expires_at` in RFC 3339, about an hour after the run starts; with `multiple = true` it's
  `<name>/<account>.json`, one per connected account (`token(name)` gives a dict, or a list with
  each `account`). The hub refreshes the token before the run; the refresh token never reaches it.
  Contract 6: only a sync job's own `secrets` are there, and a render job has none. Contracts 3
  to 5: the app's secrets, on every job.
- **Prompts** (the `prompts` grant): `/out/prompts.json`, each prompt's answers as
  `prompts/<id>/<binding>.png`, and optionally its question card `prompts/<id>/ask.png`
  (`"ask"` in prompts.json). With a question card the prompt takes its slot's whole body and the
  strip shows only the answers; without one the question goes in the strip.
- **Output:** `/out/feeds/<feed>/deck.json` and `cards/<id>.png` (exact surface size; k4: 2- or
  8-bit indexed, PLTE within the inks; g16: 8-bit grey on the sixteen levels; no tRNS, ≤ 256 KB,
  ≤ 32 cards), plus optional `prompts.json`,
  `summary.json`, `cache_key`, `timing.json` and the kit's `.metrics.json`. Contract 4:
  `result.json` (back to the UI's `jobs.run`) and `docs/<name>.json`. Contract 6, sync jobs:
  `artifacts/<name>/` (`ctx.write_artifact(name, file, value)` or `ctx.artifact_dir(name)`), each
  within its `max_kb`; render reads them with `ctx.read_artifact(name, file)` or
  `ctx.artifact(name)` (a directory, or None before the first sync).
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
  | `SLOWAPP_REMOTE_KEY_FILE` | optional (1.5.0) | A file holding the run's sealing keys (below, "Sealed runs"). The wrapper reads it and deletes it before anything else, so the job never can. Unset: nothing is sealed, as before. |
  | `SLOWAPP_REMOTE_NETWORK` | optional (1.5.0) | `none`: run the job without the network whatever the manifest says (the hub's own reading of it). `egress` never loosens the manifest. Anything else: exit 64. |

  The job child gets none of the `SLOWAPP_REMOTE_*` variables. Its `SLOWAPP_IN`, `SLOWAPP_OUT`,
  `SLOWAPP_STATE` and `SLOWAPP_CACHE` point at fresh local directories (`/cache` starts empty and
  isn't kept). `SLOWAPP_DEADLINE` means what it does on a board, the time the job's fetches fit
  into, not a kill time.
- **Requests:** GETs follow redirects; PUTs send `Content-Length` (never chunked) and
  `Content-Type` `application/x-tar` (out), `application/gzip` (data) or `text/plain;
  charset=utf-8` (log), or `application/octet-stream` for each in a sealed run, so sign only
  `host` or sign those. Each request has a 60 s timeout and is
  tried 3 times (2 s, then 4 s apart) on a network error (a broken or cut-short response
  included), 408, 429 or 5xx. Other 4xx, a link urllib can't use, a certificate that doesn't
  verify and a local file error aren't retried.
- **Archives:** an input archive is refused whole (nothing extracted) if any member has an
  absolute name or a `..`, is a device or fifo, or is a link that leaves the directory; then
  tarfile's `data` filter extracts it. `out.tar` and `data.tar.gz` hold directories and regular
  files under relative names; a symlink or special file the job made is left out and said in the
  log, and a file with several hard links goes in once per name, each a whole regular file.
- **No network for the job** (1.5.0): a job that should have none runs in an empty network
  namespace (only `lo`, up; no route) once the wrapper has fetched its inputs; the wrapper keeps
  the network for its uploads. That's a contract 6 render job (any job without `kind = "sync"`), a
  sync job whose network is `none`, any job of a contract 3 to 5 app whose `network` is `none`, or
  any job with `SLOWAPP_REMOTE_NETWORK=none`. The manifest is the image's own
  (`SLOWAPP_MANIFEST`, default `/app/slowapp.toml`); with none to read, the job keeps the network
  as before. It needs root with `CAP_SYS_ADMIN`, which a Fly Machine's root has (Docker needs
  `--cap-add SYS_ADMIN` or `--privileged`). Where it can't, the wrapper logs a line starting
  `WARNING: job <name> should run without the network` and runs the job with the network:
  `.remote.json`'s `network` says so (`isolated` false, `error` why), for the hub to act on.
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
  "started_at", "ended_at", "error", "data", "uploads_failed", "sealed", "network"}`. `job_exit` is the job's own code
  (`null` if it never ran: an input failed, the command was bad, it couldn't be started), `exit_code` what the machine exits with, times are UTC RFC 3339,
  `data` is `{"status": "none" | "saved" | "over_cap" | "failed", "loaded", "bytes", "max_mb"}`
  and `uploads_failed` lists `"data"` (and in the log, `"out"`). `sealed` is whether the run's
  objects were sealed; `network` is `{"wanted": "none" | "egress", "isolated", "error"}`.
- **Exit codes:** the job's own (0, 3, 4, 5, 64, 137, …), except **4** when an input fetch failed
  or an input archive was refused (the job didn't run; a sealed one that doesn't open included), **4** when the job ran but `/data` or
  `out.tar` didn't upload (the log and `.remote.json` say which), **64** for a bad command
  (`SLOWAPP_ENTRYPOINT` included, or one that couldn't be started), a bad `SLOWAPP_REMOTE_TIMEOUT_S`,
  `SLOWAPP_REMOTE_NETWORK` or key file, nothing to seal with, missing links, and **143** / **130** when the machine was stopped (SIGTERM / SIGINT). A failed log upload changes nothing: it shows in the machine's own log.

### Sealed runs (1.5.0)

With `SLOWAPP_REMOTE_KEY_FILE`, the store only ever holds ciphertext. The hub makes a key per run,
seals `in.tar` with it, and hands the key to the machine as a file (Fly `config.files`, never an
environment variable). The wrapper reads the file and deletes it before it fetches anything, opens
`in.tar` and the saved `/data` with it, and seals `out.tar`, `data.tar.gz` and the log. The job
child sees neither the key nor the file. A sealed run also keeps the job's own output out of the
machine's log: it goes only into the sealed log upload, and the machine's log has the wrapper's
`slowapp-remote:` lines.

- **Key file:** the key, 32 bytes in base64; or JSON `{"key": "<base64>", "data_key": "<base64>"}`.
  `data_key` (default: `key`) seals the saved `/data` both ways, so the hub can keep one per board
  or install and never has to open and re-seal `/data` between runs. A file that can't be read or
  deleted, or isn't a key, exits 64; so does a machine with nothing to seal with. Then `out.tar`
  and the log go up unsealed, holding only the wrapper's report (the job didn't run).
- **Cipher:** ChaCha20-Poly1305 (RFC 8439), from the libcrypto Python links, through ctypes; the
  `cryptography` package if that can't be loaded. The base images check it at build.
- **Format** (every object; `label` is `in`, `out`, `data` or `log`, so one can't stand in for
  another):

  ```
  header   = "SBSEAL1\n" || salt                         8 + 24 random bytes
  subkey   = HMAC-SHA256(key, "slowapp-remote seal 1" || 0x00 || label || 0x00 || salt)
  chunk i  = ChaCha20-Poly1305(subkey, nonce_i, plaintext[i·65536 … (i+1)·65536], aad = header)
             (ciphertext then the 16-byte tag)
  nonce_i  = i as 11 bytes big-endian || 0x01 for the last chunk, 0x00 before it
  ```

  Every object has at least one chunk; an empty plaintext is a single empty last chunk. A reader
  takes 65 552-byte chunks, and the one the object ends with must open as the last, so a cut,
  reordered or relabelled object doesn't open. `kit/tests/test_seal.py` builds one by hand from
  this description.
- **Refusals:** an `in.tar` or saved `/data` that doesn't open is refused like an unsafe archive
  (exit 4, the job doesn't run, `/data` isn't uploaded). The hub should likewise refuse an
  `out.tar`, `data.tar.gz` or log that doesn't open with the key it made.

## Fixture mode

`SLOWAPP_MODE=fixture`, `--network none`, no secrets (`ctx.secret()` returns `fixture-<name>`;
`ctx.token()` an access token `fixture-<name>` with the provider's scopes, and one account,
`fixture`, for `multiple`), the example's fixture as a read-only `/data` and a fixed `SLOWAPP_NOW`.
Contract 6: a render example's artifacts come from the fixture, `fixtures/<name>/artifacts/<artifact>/`
(which `ctx.read_artifact` reads when `/in/artifacts` has none), so a live sync run's
`/out/artifacts` can be copied in as it is. The same fixture must give the
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

