"""A small OCI registry client: image sizes for the catalog (`slowapp catalog release`).

Reads manifests and streams layers over the distribution API with the standard token dance
(anonymous for public images; REGISTRY_USER / REGISTRY_PASSWORD, or GITHUB_TOKEN for ghcr.io,
otherwise). Per platform it reports what a hub downloads, what that unpacks to, and how much of
both a hub that already has the base image doesn't have yet. Standard library only.
"""
import json
import os
import re
import urllib.error
import urllib.request
import zlib

INDEX_TYPES = {"application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"}
ACCEPT = ", ".join(sorted(INDEX_TYPES) + ["application/vnd.oci.image.manifest.v1+json",
                                          "application/vnd.docker.distribution.manifest.v2+json"])
PLATFORMS = ("linux/arm/v7", "linux/arm64", "linux/amd64")


class RegistryError(Exception):
    pass


def parse_ref(ref):
    """'ghcr.io/o/n:1.2@sha256:…' -> (registry, repository, reference). A digest wins over a tag."""
    m = re.fullmatch(r"([a-z0-9.-]+(?::[0-9]+)?)/([a-z0-9._/-]+?)(?::([A-Za-z0-9._-]+))?(?:@(sha256:[0-9a-f]{64}))?", ref)
    if not m:
        raise RegistryError(f"can't parse image reference {ref!r}")
    reg, repo, tag, digest = m.groups()
    return reg, repo, digest or tag or "latest"


class Registry:
    def __init__(self, registry, repo):
        self.base = f"https://{registry}/v2/{repo}"
        self.registry, self.repo = registry, repo
        self.token = None

    def _creds(self):
        user, pw = os.environ.get("REGISTRY_USER"), os.environ.get("REGISTRY_PASSWORD")
        if not pw and self.registry == "ghcr.io" and os.environ.get("GITHUB_TOKEN"):
            user, pw = os.environ.get("GITHUB_ACTOR") or "x", os.environ["GITHUB_TOKEN"]
        return (user, pw) if pw else None

    def _authenticate(self, challenge):
        m = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        if not challenge.lower().startswith("bearer") or "realm" not in m:
            raise RegistryError(f"{self.registry}: unsupported auth challenge {challenge!r}")
        q = "&".join(f"{k}={urllib.request.quote(m[k])}" for k in ("service", "scope") if k in m)
        if "scope" not in m:
            q += ("&" if q else "") + f"scope=repository:{self.repo}:pull"
        req = urllib.request.Request(f"{m['realm']}?{q}")
        creds = self._creds()
        if creds:
            import base64
            req.add_unredirected_header("Authorization", "Basic " + base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode())
        with urllib.request.urlopen(req, timeout=60) as r:
            doc = json.load(r)
        self.token = doc.get("token") or doc.get("access_token")

    def open(self, path, accept=None):
        for attempt in (0, 1):
            req = urllib.request.Request(f"{self.base}/{path}")
            if accept:
                req.add_header("Accept", accept)
            if self.token:
                # Not sent on to the blob store a registry redirects to.
                req.add_unredirected_header("Authorization", f"Bearer {self.token}")
            try:
                return urllib.request.urlopen(req, timeout=120)
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self._authenticate(e.headers.get("WWW-Authenticate", ""))
                    continue
                raise RegistryError(f"{self.registry}/{self.repo}/{path}: HTTP {e.code}") from None

    def manifest(self, reference):
        with self.open(f"manifests/{reference}", ACCEPT) as r:
            return json.load(r)

    def unpacked(self, layer):
        """Bytes a layer unpacks to (streamed, nothing kept), or None for a compression we don't read."""
        mt = layer.get("mediaType", "")
        if mt.endswith("tar"):
            return layer["size"]
        if not (mt.endswith("gzip") or mt.endswith("tar.gzip") or "gzip" in mt):
            return None
        d, n = zlib.decompressobj(16 + zlib.MAX_WBITS), 0
        with self.open(f"blobs/{layer['digest']}") as r:
            while chunk := r.read(1 << 20):
                n += len(d.decompress(chunk))
            n += len(d.flush())
        return n


def platform_name(p):
    return "/".join(x for x in (p.get("os"), p.get("architecture"), p.get("variant")) if x)


def platform_manifests(reg, reference):
    """{platform: image manifest} for an index (attestations skipped), or {"": manifest} for a single image."""
    m = reg.manifest(reference)
    if m.get("mediaType") in INDEX_TYPES or "manifests" in m:
        out = {}
        for d in m["manifests"]:
            name = platform_name(d.get("platform", {}))
            if name and "unknown" not in name:
                out[name] = reg.manifest(d["digest"])
        return out
    return {"": m}


def sizes(ref, base=None, platforms=PLATFORMS, unpack=True):
    """{platform: {download, unpacked, adds_download, adds_unpacked, layers, shared_layers}} for
    `ref`. `base` (the Dockerfile's FROM, pinned) decides which layers a hub already has."""
    reg_name, repo, reference = parse_ref(ref)
    reg = Registry(reg_name, repo)
    mine = platform_manifests(reg, reference)
    have = {}
    if base:
        b_name, b_repo, b_ref = parse_ref(base)
        breg = reg if (b_name, b_repo) == (reg_name, repo) else Registry(b_name, b_repo)
        have = {p: {l["digest"] for l in m.get("layers", [])} for p, m in platform_manifests(breg, b_ref).items()}
    out, cache = {}, {}
    for plat, m in sorted(mine.items()):
        if platforms and plat and plat not in platforms:
            continue
        layers = m.get("layers", [])
        shared = have.get(plat, have.get("", set()))
        dl = sum(l["size"] for l in layers) + m.get("config", {}).get("size", 0)
        row = {"download": dl, "layers": len(layers), "shared_layers": sum(l["digest"] in shared for l in layers),
               "adds_download": sum(l["size"] for l in layers if l["digest"] not in shared) + m.get("config", {}).get("size", 0)}
        if unpack:
            un = []
            for l in layers:
                if l["digest"] not in cache:
                    cache[l["digest"]] = reg.unpacked(l)
                un.append((l["digest"], cache[l["digest"]]))
            if all(n is not None for _, n in un):
                row["unpacked"] = sum(n for _, n in un)
                row["adds_unpacked"] = sum(n for d, n in un if d not in shared)
        out[plat or "linux/amd64"] = row
    return out
