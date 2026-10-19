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
