#!/usr/bin/env bash
# Nightly Postgres backup for the Streamload v3 stack.
#
# Dumps the database from the running `db` container via docker compose, writes
# a gzipped, timestamped file to /opt/streamload/backups, and prunes all but the
# most recent 14 backups.
#
# Install via cron (run as the deploy user). Example crontab line — runs every
# night at 03:30 server time:
#
#   30 3 * * * cd /opt/streamload/Streamload && /opt/streamload/Streamload/deploy/backup.sh >> /opt/streamload/backups/backup.log 2>&1
#
# (See docs/DEPLOY.md for the full cron setup.)
set -euo pipefail

# Dir containing docker-compose.yml + .env.prod. Defaults to the repo root
# (deploy/.. == repo root). Override with COMPOSE_DIR.
COMPOSE_DIR="${COMPOSE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/opt/streamload/backups}"
KEEP="${KEEP:-14}"

ENV_FILE="${COMPOSE_DIR}/.env.prod"
if [ ! -f "$ENV_FILE" ]; then
  echo "[backup] FATAL: $ENV_FILE not found" >&2
  exit 1
fi

# Pull POSTGRES_USER / POSTGRES_DB from .env.prod for the dump.
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a
: "${POSTGRES_USER:?POSTGRES_USER missing from .env.prod}"
: "${POSTGRES_DB:?POSTGRES_DB missing from .env.prod}"

mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="${BACKUP_DIR}/streamload_${TS}.sql.gz"

echo "[backup] $(date -Is) dumping ${POSTGRES_DB} -> ${OUT}"

# -T disables TTY allocation (required from cron). pg_dump runs inside the db
# container; output is streamed out and gzipped on the host.
docker compose -f "${COMPOSE_DIR}/docker-compose.yml" --env-file "$ENV_FILE" \
  exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  | gzip -c > "$OUT"

# Guard against a zero-byte dump (e.g. db not ready).
if [ ! -s "$OUT" ]; then
  echo "[backup] FATAL: dump is empty, removing ${OUT}" >&2
  rm -f "$OUT"
  exit 1
fi

echo "[backup] wrote $(du -h "$OUT" | cut -f1) ${OUT}"

# Prune: keep the newest $KEEP, delete the rest.
ls -1t "${BACKUP_DIR}"/streamload_*.sql.gz 2>/dev/null \
  | tail -n +"$((KEEP + 1))" \
  | while read -r old; do
      echo "[backup] pruning ${old}"
      rm -f "$old"
    done

echo "[backup] done"
