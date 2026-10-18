# Changelog

Base image releases (`vX.Y.Z` tags; README, "Versions"). Earlier releases are in the GitHub
release notes.

## Unreleased (1.4.0)

- **`slowapp-remote`: a job run from presigned links**, for the cloud hub's Fly Machines. The
  machine's command is `slowapp-remote job <name>`; the wrapper fetches `in.tar` and the board's
  saved `data.tar.gz`, runs `job <name>` as a child with local `/in`, `/out`, `/data` and
  `/cache`, then uploads `out.tar` (with `.metrics.json` and a new `.remote.json`), the new
  `/data` (within `data.max_mb`) and the log's last 64 KiB. It exits with the job's code, or 4 when
  an input fetch failed or an upload did. Standard library only. On PATH as
  `/usr/local/bin/slowapp-remote`, and every kit app takes it as its own command. The contract is
  MANIFEST.md, "Remote runs".
- CI runs the wrapper against a real S3 API (versitygw) with SigV4-presigned links.
