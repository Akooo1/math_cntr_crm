#!/bin/sh
# Prints which process this container runs: web, worker or bot (see scripts/start.sh).
name=$(printf '%s' "${PROCESS:-${RAILWAY_SERVICE_NAME:-web}}" | tr '[:upper:]' '[:lower:]')
case "$name" in
  *bot*|*telegram*) echo bot ;;
  *worker*|*cron*) echo worker ;;
  *) echo web ;;
esac
