# slowapp-python-sci: slowapp-python plus numpy, SciPy, Shapely, contourpy and tifffile, for apps
# that grid, contour or resample (weather, maps). Built FROM the slim image by digest at release,
# so a board running both kinds of app stores the slim layers once.
#
#   docker buildx build -f images/python-sci/Dockerfile --build-arg BASE=slowapp-python:dev \
#     -t slowapp-python-sci:dev .
ARG BASE=ghcr.io/mike-anderson/slowapp-python:dev
FROM ${BASE}

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3-numpy python3-scipy python3-shapely python3-contourpy python3-tifffile \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/*

# BLAS threads = 1: the board has three slow cores, and every extra thread is extra resident memory.
ENV OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

RUN python3 -c "import numpy, scipy.ndimage, shapely, contourpy, tifffile, slowapp_kit"

ARG VERSION=dev
LABEL org.opencontainers.image.title="slowapp-python-sci" \
      org.opencontainers.image.description="Slowapp base: slowapp-python plus numpy, SciPy, Shapely, contourpy, tifffile" \
      org.opencontainers.image.source="https://github.com/mike-anderson/slowapp-base" \
      org.opencontainers.image.version="${VERSION}" \
      org.slowboard.contract="6"
