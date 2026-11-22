# Matematika Markazi — operations platform

Module 1: CRM, students, payment control. Uzbek (Latin) UI. Django 5.2 + PostgreSQL 17.

- Specification and architecture: [docs/SPEC.md](docs/SPEC.md)
- Conventions for developers and AI sessions: [CLAUDE.md](CLAUDE.md)

## Run locally (one command)

Requires Docker with Compose v2.

```bash
docker compose up
```

Open http://localhost:8000. On the first start the database is migrated and demo data is
created. Demo logins (password `demo12345` for all):

| Role | Phone | Branch |
|---|---|---|
| Direktor | +998 90 000 00 01 | all |
| Filial administratori | +998 90 000 00 11 | Chilonzor filiali |
| Sotuv menejeri | +998 90 000 00 12 | Chilonzor filiali |
| O'qituvchi | +998 90 000 00 13 | Chilonzor filiali |
| Filial administratori | +998 90 000 00 21 | Yunusobod filiali |
| Sotuv menejeri | +998 90 000 00 22 | Yunusobod filiali |
| O'qituvchi | +998 90 000 00 23 | Yunusobod filiali |

The phone field accepts any format (`90 000 00 01`, `+998900000001`, ...).

To start from an empty database: `docker compose down -v && docker compose up`.

## Development without Docker

Needs Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL, gettext (`msgfmt`), Node 22
(only to build CSS).

```bash
uv sync
npm ci && npm run build:css
export POSTGRES_HOST=localhost POSTGRES_USER=mm POSTGRES_PASSWORD=mm POSTGRES_DB=matematika
uv run python manage.py migrate
uv run python manage.py createcachetable
uv run python manage.py compilemessages -l uz --ignore=.venv --ignore=node_modules
uv run python manage.py seed_demo
uv run python manage.py runserver
```

## Checks (same as CI)

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run lint-imports
uv run python manage.py makemigrations --check --dry-run
scripts/i18n.sh --check
```

## UI text

All text lives in `locale/uz/LC_MESSAGES/django.po`. After adding or changing UI strings,
run `scripts/i18n.sh`, fill in every new `msgstr`, and commit the `.po` file. Tests fail if
a string is untranslated or English reaches a page.
