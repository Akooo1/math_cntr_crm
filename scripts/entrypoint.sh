#!/bin/sh
# Container start: wait for PostgreSQL, apply migrations, then run the command.
set -e

# Started as root (Railway with RAILWAY_RUN_UID=0 mounts volumes owned by root): give the
# uploads folder to the app user, then continue as that user. Never run the app as root.
if [ "$(id -u)" = "0" ] && id app >/dev/null 2>&1; then
  mkdir -p /app/media && chown -R app /app/media
  exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

echo "Waiting for the database..."
python manage.py wait_for_db --timeout 120

# Only the website migrates; the worker and the bot never do (also when SKIP_MIGRATE is unset).
process=$(scripts/process.sh)
echo "Process: $process"
if [ "${SKIP_MIGRATE:-0}" != "1" ] && [ "$process" = "web" ]; then
  # Production: before an update changes the database, back it up to the Direktor's Telegram.
  # If that fails, stop here: the database is not touched and the old version keeps running.
  # BACKUP_BEFORE_MIGRATE: auto (default: on in production when a bot token is set), 1, 0.
  case "${BACKUP_BEFORE_MIGRATE:-auto}" in
    1) backup=1 ;;
    0) backup=0 ;;
    *) case "$DJANGO_SETTINGS_MODULE" in
         *prod*) [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && backup=1 || backup=0 ;;
         *) backup=0 ;;
       esac ;;
  esac
  if [ "$backup" = "1" ]; then
    python manage.py backup_to_telegram --before-migrate || {
      echo "Backup before the update FAILED (see above). Database changes were NOT applied."
      echo "Fix the cause, or set BACKUP_BEFORE_MIGRATE=0 on this service to skip it once."
      exit 1
    }
  fi
  python manage.py migrate --noinput
  python manage.py createcachetable
  # Hosts without a shell (Railway): create the first Direktor from variables, once.
  # The password must be changed at the first login; then delete DIRECTOR_PASSWORD.
  if [ -n "${DIRECTOR_PHONE:-}" ] && [ -n "${DIRECTOR_PASSWORD:-}" ]; then
    python manage.py create_director --if-none --must-change \
      --phone "$DIRECTOR_PHONE" --name "${DIRECTOR_NAME:-Direktor}" --password "$DIRECTOR_PASSWORD" \
      || echo "First Direktor was NOT created: see the message above."  # never block start-up
  fi
fi

case "$DJANGO_SETTINGS_MODULE" in
  *dev*) if command -v msgfmt >/dev/null; then
           python manage.py compilemessages -l uz --ignore=node_modules >/dev/null
         fi ;;
esac

# Demo data only with the dev settings (docker compose locally); production settings don't
# even have the command, so DEMO_SEED=1 set there by mistake does nothing.
if [ "${DEMO_SEED:-0}" = "1" ]; then
  case "$DJANGO_SETTINGS_MODULE" in
    *dev*) python manage.py seed_demo ;;
    *) echo "DEMO_SEED ignored: demo data is only for local development." ;;
  esac
fi

exec "$@"
