#!/bin/sh
set -e

echo "[entrypoint] Running migrations..."
alembic upgrade head

echo "[entrypoint] Starting Streamload API server..."
exec granian \
    --interface asgi \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --loop uvloop \
    streamload.api.app:app
