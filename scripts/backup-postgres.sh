#!/bin/bash
# Daily Postgres backup, keep last 14 days.
# Usage: run via systemd timer (see docs/deploy.md) or cron.
set -e

BACKUP_DIR="/opt/streamload/data/backups"
mkdir -p "$BACKUP_DIR"

DATE=$(date +%Y-%m-%d)
BACKUP_FILE="$BACKUP_DIR/streamload-$DATE.sql.gz"

docker exec streamload-postgres pg_dump -U streamload streamload | \
    gzip > "$BACKUP_FILE"

# Prune older than 14 days
find "$BACKUP_DIR" -name "streamload-*.sql.gz" -mtime +14 -delete

echo "Backup complete: $BACKUP_FILE ($(du -sh "$BACKUP_FILE" | cut -f1))"
