#!/bin/sh
# Streamload v3 backend container entrypoint.
#
# 1. Apply DB migrations. The app's lifespan does NOT run alembic (it only
#    bootstraps the admin user + starts the catalog worker), so migrations MUST
#    run here before the server starts.
#
#    Alembic's migrations/env.py reads DATABASE_URL directly and drives an
#    ASYNC engine (async_engine_from_config) with the asyncpg driver. It does
#    NOT strip "+asyncpg" — so we pass the SAME asyncpg DATABASE_URL the app
#    uses, unchanged. No separate sync/psycopg URL is needed.
#
# 2. Start granian, bound to 0.0.0.0:8000 so Caddy (on the compose network) can
#    reach it. 1 worker by default (1 vCPU / 2 GB droplet); override with
#    GRANIAN_WORKERS.
set -e

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] FATAL: DATABASE_URL is not set" >&2
  exit 1
fi

echo "[entrypoint] Running migrations (alembic upgrade head)..."
alembic upgrade head

echo "[entrypoint] Starting Streamload API (granian, workers=${GRANIAN_WORKERS:-1})..."
# NOTE: no `--loop uvloop`. uvloop ships no cp314 wheel, so on the python:3.14
# base image granian crashes at worker spawn ("'uvloop' implementation not
# available"). Granian's default loop (asyncio) is correct here; the small
# throughput edge from uvloop is irrelevant for ~10 users.
exec granian \
    --interface asgi \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${GRANIAN_WORKERS:-1}" \
    streamload.api.app:app
