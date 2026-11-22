#!/usr/bin/env bash
# Extract UI strings into locale/uz/LC_MESSAGES/django.po and compile.
# --check: fail if extraction would change the catalog (new or removed strings).
set -euo pipefail
cd "$(dirname "$0")/.."
PO=locale/uz/LC_MESSAGES/django.po
IGNORES=(--ignore=node_modules --ignore=.venv --ignore=staticfiles --ignore=static)
if [[ "${1:-}" == "--check" ]]; then
  before=$(grep -E '^msgid ' "$PO" | sort)
  python manage.py makemessages -l uz --no-obsolete --no-location "${IGNORES[@]}" >/dev/null
  after=$(grep -E '^msgid ' "$PO" | sort)
  if [[ "$before" != "$after" ]]; then
    echo "UI strings changed. Run scripts/i18n.sh, translate the new msgids and commit." >&2
    diff <(echo "$before") <(echo "$after") >&2 || true
    exit 1
  fi
  echo "i18n catalog is up to date."
  exit 0
fi
python manage.py makemessages -l uz --no-obsolete --no-location "${IGNORES[@]}"
# msgmerge "fuzzy"-guesses new strings from similar old ones, often wrongly. Blank them so
# every new msgid is translated by a person.
msgattrib --clear-fuzzy --empty -o "$PO" "$PO"
python manage.py compilemessages -l uz --ignore=.venv --ignore=node_modules
