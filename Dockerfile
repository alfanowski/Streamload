# syntax=docker/dockerfile:1.7

# ============================================================
# Stage 1: Backend wheel builder
# ============================================================
FROM python:3.11-slim AS backend-builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    pkg-config \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --user --no-cache-dir --no-warn-script-location -r requirements.txt

# ============================================================
# Stage 2: Runtime
# ============================================================
FROM python:3.11-slim AS runtime

# System deps: ffmpeg (post-processing), libchromaprint-tools (skip intro),
# libpq5 (asyncpg), CA certs, tini (PID 1 / signal forwarding).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libchromaprint-tools \
    libpq5 \
    ca-certificates \
    tini \
 && rm -rf /var/lib/apt/lists/*

# Non-root user (uid 1000 to match typical host user)
RUN useradd -m -u 1000 streamload
WORKDIR /app

# Copy backend Python deps
COPY --from=backend-builder --chown=streamload:streamload /root/.local /home/streamload/.local
ENV PATH="/home/streamload/.local/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy backend source
COPY --chown=streamload:streamload streamload/ ./streamload/
COPY --chown=streamload:streamload alembic.ini ./
COPY --chown=streamload:streamload migrations/ ./migrations/
COPY --chown=streamload:streamload streamload.py ./

# Entrypoint runs migrations then exec's Granian (signal-safe)
COPY --chown=streamload:streamload entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import httpx, sys; r = httpx.get('http://localhost:8000/api/health', timeout=3); sys.exit(0 if r.status_code == 200 else 1)" || exit 1

USER streamload
EXPOSE 8000

ENTRYPOINT ["tini", "--", "./entrypoint.sh"]
