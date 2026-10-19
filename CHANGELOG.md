# Changelog

Base image releases (`vX.Y.Z` tags; README, "Versions"). Earlier releases are in the GitHub
release notes.

## Unreleased (1.5.0)

Contract 6: the sync/render split and per-job secrets (the secrets track's S2, S3 and S5 halves in
this repo). Contracts 3 to 5 keep working unchanged.

- **Manifest.** `[secrets.<name>]` (`kind = "value" | "oauth"`, `label`, `help`, `optional`, and
  for OAuth `auth` and `multiple`), `[auth.<provider>]` (`authorize_url`, `token_url`,
  `revoke_url`, `scopes`, `pkce`, `params`), `[artifacts.<name>] max_kb`, and on `[[job]]`: `kind
  = "sync" | "render"` (default render), `network` and `secrets` (sync only), and `min_every` next
  to a sync job's `every`. A render job that declares secrets or a network is a validator error,
  as are app-level `secrets` in a contract 6 manifest; before contract 6 they still read as value
  secrets on every job. The SDK's schema and validator, the catalog's grants (`oauth`, and the
  network from the jobs) and the catalog schema (contracts 3 to 6) follow.
- **Kit.** Contract 6 is accepted (`SLOWAPP_CONTRACT` 3 to 6). `token(name)` / `ctx.token(name)`
  reads an oauth secret's access token, `/run/secrets/<name>.json` as a dict, or with `multiple`
  each `/run/secrets/<name>/<account>.json` as a list (each with its `account`); missing is exit 5
  unless optional, and fixture mode gives placeholders. `secret()` is unchanged (and refuses an
  oauth secret). Sync jobs write artifacts with `ctx.write_artifact(name, file, value)` (or
  `ctx.artifact_dir(name)`), checked against `[artifacts]` and `max_kb` when the job ends; render
  reads them with `ctx.read_artifact(name, file)` / `ctx.artifact(name)` from
  `/in/artifacts/<name>/`, or in fixture mode from the fixture's `artifacts/`. What it reads counts
  towards `exit_if_unchanged`. `ctx.kind` and `slowapp_kit.manifest.job_spec` say what a job is
  granted.
- **`slowapp-remote`: no network for render.** A job that should have no network (a contract 6
  render job, a sync job with `network = "none"`, any job of an older app whose network is none,
  or `SLOWAPP_REMOTE_NETWORK=none`) runs in an empty network namespace (`os.unshare`, only `lo`)
  once its inputs are fetched. It needs root with `CAP_SYS_ADMIN`, as on a Fly Machine; elsewhere
  the wrapper logs a `WARNING:` line and runs it with the network, and `.remote.json` says so
  (`network.isolated`). Contract 5 apps such as weather keep their network.
- **`slowapp-remote`: sealed runs.** With `SLOWAPP_REMOTE_KEY_FILE` (read, then deleted before
  anything runs), `in.tar` and the saved `/data` are opened and `out.tar`, `data.tar.gz` and the
  log are sealed: ChaCha20-Poly1305 in 64 KiB STREAM chunks from the libcrypto Python already links
  (ctypes; the images gain no package), format in MANIFEST.md, "Sealed runs". An optional
  `data_key` seals `/data` across runs. A sealed run keeps the job's output out of the machine's
  log. Without the variable, nothing changes.
- **JS: bridge protocol 2.** `protocol.json` adds `secrets.connect(name)` → `{url}` (the hub's page
  starts the sign-in at top level; the frame never sees the provider's URL, code or state), a
  `secret` event, the error `kind`, and a wider `secrets.status` (`kind`, `label`, `help`,
  `last_used`, and for oauth `auth`, `multiple`, `scopes`, `granted_at`, `accounts`);
  `secrets.clear` takes an account. The handshake still says protocol 1, so protocol 1 bundles
  keep connecting: an app says 2 in its `connect` call and the chrome answers the protocol both
  speak (`app.protocol`). `@slowboard/app` gains `secrets.connect` and `secrets.watch`,
  `@slowboard/app-react`'s `useSecrets` gains `connect` and follows the events, and
  `@slowboard/ui/secrets` adds `<sb-secret-field>` and `<sb-connect>` (framework-free, CSP-clean).
  `@slowboard/dev` fakes the sign-in, gives each job only its own secrets (oauth as dev tokens),
  runs render without the network and carries a sync run's artifacts to the next render.
- **Images:** `SLOWAPP_CONTRACT=6` and the label `org.slowboard.contract=6` (it said 4, and the
  description "contracts 3 and 4"); the build checks that sealing works on each platform.

## 1.4.1

- `check_inks` (so `encode_png`, `to_grey`, `codes`) asks PIL's `getcolors` for just past the ink
  set's colours instead of 2^24. PIL sizes its table by that limit, so the old call took hundreds
  of MB and raised MemoryError on a 512 MB cloud-hub run machine. A picture with more colours than
  the inks is still an `InkError`. The SDK's catalog `inks()` likewise asks for 64.

## 1.4.0

- **`slowapp-remote`: a job run from presigned links**, for the cloud hub's Fly Machines. The
  machine's command is `slowapp-remote job <name>`; the wrapper fetches `in.tar` and the board's
  saved `data.tar.gz`, runs `job <name>` as a child with local `/in`, `/out`, `/data` and
  `/cache`, then uploads `out.tar` (with `.metrics.json` and a new `.remote.json`), the new
  `/data` (within `data.max_mb`) and the log's last 64 KiB. It exits with the job's code, or 4 when
  an input fetch failed or an upload did. Standard library only. On PATH as
  `/usr/local/bin/slowapp-remote`, and every kit app takes it as its own command. The contract is
  MANIFEST.md, "Remote runs".
  - The hub decides whether saved `/data` exists: `SLOWAPP_REMOTE_DATA_GET` when it does,
    `SLOWAPP_REMOTE_DATA_NEW=1` (and no GET) when it doesn't. `/data` is uploaded only after one of
    the two, so a `DATA_PUT` alone can't put an empty `/data` over saved data; a 403 on the GET
    fails the run like any other error, a 404 still starts empty.
  - SIGTERM or SIGINT stops the job child (SIGTERM, SIGKILL 3 s later), still uploads, and exits
    143 or 130.
  - `SLOWAPP_REMOTE_TIMEOUT_S` of 0 or less means no limit; one that isn't a number exits 64, as
    does a `SLOWAPP_ENTRYPOINT` that isn't a non-empty JSON list of strings (on both the kit's and
    the standalone path) and a job command that can't be started (`job_exit` null, `/data` not
    uploaded).
  - Broken HTTP responses (a bad status line, a body cut short) are retried like network errors;
    local file errors, unusable links and certificate failures aren't. Hard-linked files go into
    the tars as regular files.
- CI runs the wrapper against a real S3 API (versitygw) with SigV4-presigned links.
