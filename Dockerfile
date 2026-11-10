# syntax=docker/dockerfile:1.7
# WorkForce – ein Image für Web, Worker und Scheduler (gleiche Codebasis, unterschiedliche Kommandos).
# Basis-Images sind per Tag + Digest gepinnt (Stand 2026-11-10); Aktualisierung siehe docs/betrieb.md.
ARG NODE_IMAGE=node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d
ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c

# ---------- Oberfläche bauen -----------------------------------------------------------------------
FROM ${NODE_IMAGE} AS frontend
WORKDIR /src
COPY docker/extra-ca.sh /usr/local/bin/extra-ca
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=extra_ca,required=false . extra-ca && npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${UV_IMAGE} AS uv

# ---------- Laufzeit ---------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
# Chromium (Playwright) wird für öffentlich angebotene Tabellenexporte der amtlichen Statistik benötigt.
# Mit --build-arg INSTALL_BROWSER=0 entfällt er (dann nur manueller Dateiimport für diese Tabellen).
ARG INSTALL_BROWSER=1
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright PATH="/app/.venv/bin:${PATH}" \
    WF_STATIC_DIR=/app/static WF_DATA_DIR=/data
COPY docker/extra-ca.sh /usr/local/bin/extra-ca
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
RUN --mount=type=secret,id=extra_ca,required=false . extra-ca \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends tini curl \
    && rm -rf /var/lib/apt/lists/*
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=secret,id=extra_ca,required=false . extra-ca \
    && uv sync --frozen --no-dev --no-install-project
RUN --mount=type=secret,id=extra_ca,required=false . extra-ca \
    && if [ "$INSTALL_BROWSER" = "1" ]; then \
         apt-get update && playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*; \
       fi
COPY backend/ ./
RUN --mount=type=secret,id=extra_ca,required=false . extra-ca && uv sync --frozen --no-dev
COPY --from=frontend /src/dist /app/static
RUN groupadd --system --gid 10001 workforce && useradd --system --uid 10001 --gid workforce --home-dir /app workforce \
    && mkdir -p /data && chown -R workforce:workforce /data
USER workforce
VOLUME ["/data"]
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--", "workforce"]
CMD ["web"]
