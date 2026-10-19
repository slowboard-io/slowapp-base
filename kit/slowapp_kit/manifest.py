"""What a manifest grants one job (MANIFEST.md, contract 6). Standard library only: the remote
wrapper uses it too.

Contract 6 splits jobs in two. A sync job (`kind = "sync"`) gets its own `network` (default: the
app's) and the secrets it lists; a render job (every other job) gets no network and no secrets.
Before contract 6 a job has no kind: every job has the app's network and its secrets.
"""

import re

KINDS = ("sync", "render")
ARTIFACT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def contract(m):
    try:
        return int((m or {}).get("app", {}).get("contract", 3))
    except (TypeError, ValueError):
        return 3


def job_decl(m, name):
    """The [[job]] table named `name`, or {} if the manifest doesn't declare it."""
    return next((j for j in (m or {}).get("job", []) if isinstance(j, dict) and j.get("name") == name), {})


def job_spec(m, name):
    """{"kind", "network", "secrets"} for job `name`. kind is "sync" or "render" from contract 6
    on, None before (a job of both kinds). network is "none" or "egress"."""
    app = (m or {}).get("app", {})
    j = job_decl(m, name)
    if contract(m) < 6:
        return {"kind": None, "network": app.get("network", "none"),
                "secrets": list(app.get("secrets", [])) + list(app.get("optional_secrets", []))}
    kind = j.get("kind", "render")
    if kind != "sync":
        return {"kind": "render", "network": "none", "secrets": []}
    return {"kind": "sync", "network": j.get("network", app.get("network", "none")),
            "secrets": list(j.get("secrets", []))}


def secret_decl(m, name):
    """[secrets.<name>] (contract 6), or {} when undeclared (a contract 3 to 5 secret is a value)."""
    s = (m or {}).get("secrets")
    return s.get(name, {}) if isinstance(s, dict) else {}
