#!/bin/sh
# Container start: wait for PostgreSQL, apply migrations, then run the command.
set -e

echo "Waiting for PostgreSQL at ${POSTGRES_HOST:-db}..."
python manage.py wait_for_db --timeout 120

if [ "${SKIP_MIGRATE:-0}" != "1" ]; then
  python manage.py migrate --noinput
  python manage.py createcachetable
fi

case "$DJANGO_SETTINGS_MODULE" in
  *dev*) if command -v msgfmt >/dev/null; then
           python manage.py compilemessages -l uz --ignore=node_modules >/dev/null
         fi ;;
esac

if [ "${DEMO_SEED:-0}" = "1" ]; then
  python manage.py seed_demo
fi

exec "$@"
