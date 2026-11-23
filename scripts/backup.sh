#!/bin/sh
# Database + uploaded-files backup with rotation.
#
# In production the `backup` container runs this every night at 02:30 (Asia/Tashkent).
# Run it by hand on the server with:
#   scripts/backup.sh
# (on the host it re-runs itself inside the backup container).
#
# Output in $BACKUP_DIR:
#   daily/db_YYYY-MM-DD_HHMM.dump        pg_dump custom format (restore: scripts/restore.sh)
#   daily/media_YYYY-MM-DD_HHMM.tar.gz   uploaded Excel files
#   weekly/...                           a copy of Sunday's backup
# Rotation keeps the newest $KEEP_DAILY daily and $KEEP_WEEKLY weekly sets; older files in
# those two folders are removed. Copy backups off the server regularly (see README).
set -eu

if ! command -v pg_dump >/dev/null 2>&1; then
  # On the host: run inside the backup container, which has the matching pg_dump.
  cd "$(dirname "$0")/.."
  exec docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backup /scripts/backup.sh
fi

DIR="${BACKUP_DIR:-/backups}"
MEDIA="${MEDIA_DIR:-/media}"
KEEP_DAILY="${KEEP_DAILY:-14}"
KEEP_WEEKLY="${KEEP_WEEKLY:-8}"
STAMP="$(date +%Y-%m-%d_%H%M)"

mkdir -p "$DIR/daily" "$DIR/weekly"

DB_FILE="$DIR/daily/db_$STAMP.dump"
pg_dump --format=custom --compress=6 --no-owner --file="$DB_FILE.partial"
# A dump that pg_restore can't list is not a backup.
pg_restore --list "$DB_FILE.partial" >/dev/null
mv "$DB_FILE.partial" "$DB_FILE"
echo "backup: database -> $DB_FILE ($(du -h "$DB_FILE" | cut -f1))"

if [ -d "$MEDIA" ] && [ -n "$(ls -A "$MEDIA" 2>/dev/null)" ]; then
  MEDIA_FILE="$DIR/daily/media_$STAMP.tar.gz"
  tar -czf "$MEDIA_FILE" -C "$MEDIA" .
  echo "backup: media -> $MEDIA_FILE"
fi

if [ "$(date +%u)" = "7" ]; then
  cp "$DB_FILE" "$DIR/weekly/"
  [ -f "$DIR/daily/media_$STAMP.tar.gz" ] && cp "$DIR/daily/media_$STAMP.tar.gz" "$DIR/weekly/"
  echo "backup: weekly copy made"
fi

# Rotation: keep the newest N of each kind in each folder.
prune() {
  folder="$1"; pattern="$2"; keep="$3"
  # shellcheck disable=SC2012 - names have no spaces (fixed format)
  ls -1t "$folder"/$pattern 2>/dev/null | tail -n +"$((keep + 1))" | while read -r old; do
    rm -f -- "$old"
    echo "backup: rotated out $old"
  done
}
prune "$DIR/daily" "db_*.dump" "$KEEP_DAILY"
prune "$DIR/daily" "media_*.tar.gz" "$KEEP_DAILY"
prune "$DIR/weekly" "db_*.dump" "$KEEP_WEEKLY"
prune "$DIR/weekly" "media_*.tar.gz" "$KEEP_WEEKLY"

echo "backup: done"
