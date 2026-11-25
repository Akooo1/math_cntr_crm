#!/bin/sh
# The image's default command: run the website, the scheduled jobs or the Telegram bot.
# Chosen by PROCESS (web | worker | bot); on Railway it falls back to the service's name, so
# a service named "bot" or "worker" works even when its config file isn't picked up.
# Explicit commands (Docker Compose, deploy/railway/*.json) don't use this file.
set -e

case "$(scripts/process.sh)" in
  bot)
    scripts/health_server.sh
    exec python manage.py telegram_bot ;;
  worker)
    scripts/health_server.sh
    exec /usr/local/bin/supercronic -passthrough-logs /app/deploy/crontab ;;
  *)
    exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${WEB_CONCURRENCY:-3}" --access-logfile - ;;
esac
