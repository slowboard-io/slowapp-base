# The example slowapp, as the base repo's smoke test: CI builds it on the slowapp-python it just
# built (--build-arg BASE). The slowapp-example repo pins a released base by tag and digest instead.
ARG BASE=slowapp-python:dev
FROM ${BASE}
COPY slowapp.toml /app/slowapp.toml
COPY moon /opt/app/moon
# The UI (contract 4 [ui] entry): ui/dist/index.html, built first (`npm run build:example` at the
# repo root; CI does). The slowapp-example template builds it in a node stage instead.
COPY ui/dist/index.html /ui/index.html
ENV PYTHONPATH=/opt/app:/opt/slowapp
RUN python3 -m compileall -q /opt/app
ENTRYPOINT ["python3", "-m", "moon"]
CMD ["job", "render"]
