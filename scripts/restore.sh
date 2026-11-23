#!/bin/sh
# Restore a backup made by scripts/backup.sh. THIS REPLACES ALL CURRENT DATA.
#
#   scripts/restore.sh backups/daily/db_2026-11-23_0230.dump [backups/daily/media_...tar.gz]
#
# Run on the server from the project folder. The web and cron containers are stopped
# during the restore and started again afterwards.
set -eu

if [ "$#" -lt 1 ] || [ ! -f "$1" ]; then
  echo "usage: $0 <db_*.dump> [media_*.tar.gz]" >&2
  exit 1
fi
DUMP="$1"
MEDIA_ARCHIVE="${2:-}"
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

echo "This will REPLACE the whole database with: $DUMP"
[ -n "$MEDIA_ARCHIVE" ] && echo "and the uploaded files with: $MEDIA_ARCHIVE"
printf "Type RESTORE to continue: "
read -r answer
[ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 1; }

# Safety net: a fresh backup of the current state first.
scripts/backup.sh

$COMPOSE stop web cron
# --clean drops and recreates every object, including the append-only triggers.
$COMPOSE exec -T backup sh -c 'pg_restore --clean --if-exists --no-owner --dbname="$PGDATABASE"' < "$DUMP"
if [ -n "$MEDIA_ARCHIVE" ]; then
  $COMPOSE run --rm --no-deps -T --user root --entrypoint sh web \
    -c 'find /app/media -mindepth 1 -delete && tar -xzf - -C /app/media && chown -R app /app/media' < "$MEDIA_ARCHIVE"
fi
$COMPOSE start web cron
echo "Restore finished. Log in and check the data."
