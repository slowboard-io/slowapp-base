# slowapp-base

Base images, the Python kit and the SDK for **slowapps**: the language-agnostic containers that
draw content for a Slowboard e-paper dashboard. The board's daemons (slowbd, slowbhub) and the
contract's design live in [epaper-dashboard](https://github.com/mike-anderson/epaper-dashboard)
(`docs/SLOWBOARD.md` §8). The manifest reference is [MANIFEST.md](MANIFEST.md).

## Images

| Image | What's in it | For |
|---|---|---|
| `ghcr.io/mike-anderson/slowapp-python` | Debian trixie-slim, Python 3, Pillow, `slowapp_kit`, the SDK, fonts (DejaVu, Alfa Slab One) | most apps |
| `ghcr.io/mike-anderson/slowapp-python-sci` | `slowapp-python` + numpy, SciPy, Shapely, contourpy, tifffile; BLAS threads pinned to 1 | weather, maps |

- **Layered:** `-sci` is built `FROM` the slim image's exact digest at release, so a board that
  runs both kinds of app stores the slim layers once.
- **Platforms:** `linux/arm/v7` (the Lyra), `linux/arm64`, `linux/amd64`. The libraries come from
  Debian's packages, because PyPI has few 32-bit ARM wheels.
- **Contract:** label `org.slowboard.contract=3`, and `SLOWAPP_CONTRACT=3` in the environment.

### Versions

Both images release together, with tags `X.Y.Z`, `X.Y` and `X` from a git tag `vX.Y.Z`. There is
no `latest`.

- **Patch:** a rebuild or a fix. The monthly `rebuild` workflow cuts one, so Debian security
  updates land without anyone remembering to.
- **Minor:** something added to the kit or SDK, or a new library in an image.
- **Major:** a contract change (a new `contract` number in the manifest).

Apps pin a tag and a digest in their Dockerfile, and Dependabot opens the bump PR:

```dockerfile
FROM ghcr.io/mike-anderson/slowapp-python:1.0.0@sha256:…
```

Releasing by hand: `git tag v1.1.0 && git push origin v1.1.0`, or run the `release` workflow. The
release notes list both digests.

## Making an app

Start from [slowapp-example](https://github.com/mike-anderson/slowapp-example), a template
repository: the moon's phase, Pillow only, no network. An app repo holds:

```
slowapp.toml     the manifest: grants, jobs, feeds, examples (MANIFEST.md)
Dockerfile       FROM a pinned base; COPY the manifest to /app/slowapp.toml and the code anywhere
<module>/        the code; `import slowapp_kit as kit`, `@kit.job("render")`, `kit.main()`
fixtures/<name>/ /data for each [[example]]
tests/           unit tests, run inside the base image
.github/workflows/app.yml   ten lines that call this repo's reusable workflow
```

The reusable workflow [`.github/workflows/app.yml`](.github/workflows/app.yml) runs these steps:
1. Takes the SDK out of the base image the Dockerfile pins, so an app is always checked by the
   tools that match its base.
2. Validates the manifest and runs the unit tests inside the base.
3. Builds the image and runs every example in fixture mode twice, requiring identical pixels.
4. Uploads the previews.
5. Builds for armv7.
6. On a `vX.Y.Z` tag, pushes the image for all three platforms and writes the digest to pin in
   `slowbhub.toml` into the release notes.

Locally, with Docker or Podman:

```sh
docker build -t slowapp-moon:dev .
docker create --name sdk ghcr.io/mike-anderson/slowapp-python:1 && docker cp sdk:/opt/slowapp /tmp/slowapp && docker rm sdk
PYTHONPATH=/tmp/slowapp python3 -m slowapp_sdk validate
PYTHONPATH=/tmp/slowapp python3 -m slowapp_sdk fixture --image slowapp-moon:dev --repeat   # needs Pillow
```

Set `SLOWAPP_PLATFORM=linux/arm/v7` to run the board's image under QEMU.

## This repo

```
images/python/Dockerfile       slowapp-python
images/python-sci/Dockerfile   slowapp-python-sci (ARG BASE)
kit/slowapp_kit/               the app side of the contract: context, output checks, jobs, UI server
sdk/slowapp_sdk/               `python3 -m slowapp_sdk validate|fixture`, and the manifest schema
example/                       the moon app, the images' smoke test (the template repo's twin)
fonts/                         baked into the images at /opt/slowapp/fonts (licences alongside)
```

Tests: `PYTHONPATH=kit:sdk:example python3 -m unittest discover -s kit/tests` (likewise
`sdk/tests` and `example/tests`). CI also runs them inside the images and on armv7.
