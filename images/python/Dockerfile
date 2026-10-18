# slowapp-python: the slim base every Python app starts FROM. Debian trixie's Python 3 and Pillow,
# slowapp_kit (the app side of the contract), the slowapp SDK (validate, fixture) and the fonts.
# Heavy libraries go in slowapp-python-sci, built FROM this image so the layers are shared.
#
#   docker buildx build -f images/python/Dockerfile -t slowapp-python:dev .
#
# Debian's armhf packages, not PyPI: PyPI has few 32-bit ARM wheels. The Debian base is pinned
# by digest in the FROM line itself, so Dependabot can bump it.
FROM docker.io/library/debian:trixie-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pil tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/*

ENV PYTHONPATH=/opt/slowapp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SLOWAPP_CONTRACT=4 \
    SLOWAPP_FONTS=/opt/slowapp/fonts \
    SLOWAPP_MANIFEST=/app/slowapp.toml \
    TZ=America/Vancouver

COPY fonts /opt/slowapp/fonts
COPY kit/slowapp_kit /opt/slowapp/slowapp_kit
COPY sdk/slowapp_sdk /opt/slowapp/slowapp_sdk

# Bytecode is compiled now, at build: the root filesystem is read-only at run time.
RUN python3 -m compileall -q /opt/slowapp \
 && python3 -c "import slowapp_kit, slowapp_sdk, PIL"

ARG VERSION=dev
LABEL org.opencontainers.image.title="slowapp-python" \
      org.opencontainers.image.description="Slowapp base: Debian trixie, Python 3, Pillow, slowapp_kit (contracts 3 and 4)" \
      org.opencontainers.image.source="https://github.com/mike-anderson/slowapp-base" \
      org.opencontainers.image.version="${VERSION}" \
      org.slowboard.contract="4"

WORKDIR /tmp
