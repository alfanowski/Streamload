# syntax=docker/dockerfile:1.7
#
# Streamload v3 backend — production image.
#
# Base: python:3.14-slim. If the 3.14 tag is ever unavailable in your registry,
# fall back to python:3.13-slim (both are Debian-slim and compatible). Set via
# the PY_BASE build arg so CI / the VPS can override without editing this file.
ARG PY_BASE=python:3.14-slim

# ============================================================
# Stage 1: dependency builder (wheels into --user)
# ============================================================
FROM ${PY_BASE} AS backend-builder

WORKDIR /app

# build-essential + libpq-dev: build asyncpg / argon2-cffi / cryptography wheels
# if a prebuilt wheel is unavailable for the platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    pkg-config \
 && rm -rf /var/lib/apt/lists/*

# Cache the dependency layer: only re-runs when requirements.txt changes.
COPY requirements.txt ./
RUN pip install --user --no-cache-dir --no-warn-script-location -r requirements.txt

# ============================================================
# Stage 2: runtime
# ============================================================
FROM ${PY_BASE} AS runtime

# Runtime system deps:
#   ffmpeg, libchromaprint-tools -> media post-processing / intro detection
#   libpq5                       -> asyncpg runtime
#   curl                         -> container HEALTHCHECK
#   ca-certificates              -> TLS to TMDB/Resend
#   tini                         -> PID 1 / signal forwarding to granian
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libchromaprint-tools \
    libpq5 \
    curl \
    ca-certificates \
    tini \
 && rm -rf /var/lib/apt/lists/*

# Non-root user.
RUN useradd -m -u 1000 streamload
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/home/streamload/.local/bin:$PATH"

# Copy installed Python deps from the builder.
COPY --from=backend-builder --chown=streamload:streamload /root/.local /home/streamload/.local

# Copy application source. The package lives at the repo root (streamload/), and
# alembic.ini uses script_location=%(here)s/migrations with prepend_sys_path=.,
# so the working dir IS the import root — no src/ layout, no PYTHONPATH needed.
COPY --chown=streamload:streamload streamload/ ./streamload/
COPY --chown=streamload:streamload migrations/ ./migrations/
COPY --chown=streamload:streamload alembic.ini ./
COPY --chown=streamload:streamload streamload.py ./

# Entrypoint: alembic upgrade head, then exec granian.
COPY --chown=streamload:streamload deploy/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

EXPOSE 8000

# Healthcheck hits the app's health router. NOTE: openapi/health are mounted
# under /api (openapi_url="/api/openapi.json", health at GET /api/health).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

USER streamload

# tini forwards SIGTERM to granian for clean shutdown (lifespan teardown).
ENTRYPOINT ["tini", "--", "./entrypoint.sh"]
