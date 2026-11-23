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

## Production on Railway

Step by step: [docs/deploy-railway.md](docs/deploy-railway.md) (web, worker, bot and
Railway's PostgreSQL; about $7–12 a month).

## Production (one Linux VPS)

Needs Docker with Compose v2, a domain whose DNS A record points at the server, and ports
80 and 443 open. Caddy gets the Let's Encrypt certificate by itself.

1. Copy the project to the server and create the settings file:

   ```bash
   cp .env.example .env
   ```

   Fill in `DOMAIN`, a long random `POSTGRES_PASSWORD` and `DJANGO_SECRET_KEY`. For example:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

2. Build and start:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```

   Services: `db` (PostgreSQL 17), `web` (gunicorn; migrates on start), `cron` (monthly
   charges 00:10, lesson calendars 00:20, session cleanup 03:40), `backup` (02:30), `caddy`
   (HTTPS). No demo data is loaded in production. Django admin is not available.

3. Create the first Direktor (asks for the password if `--password` is left out):

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py create_director --phone "90 123 45 67" --name "Familiya Ism"
   ```

   Log in at `https://<DOMAIN>/`, then set up branches, courses, prices and users in
   Sozlamalar.

4. Update to a new version:

   ```bash
   git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```

### Telegram bot

1. In Telegram, open @BotFather, send `/newbot`, choose a name and a username ending in
   `bot`. BotFather replies with a token like `123456789:AA...`.
2. On the server, put it into `.env` (never into a chat or into git):

   ```bash
   TELEGRAM_BOT_TOKEN=123456789:AA...
   ```

3. Restart: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
4. In the app: Sozlamalar → Telegram shows "Bot ishlayapti: @your_bot". Press
   "Telegramimni ulash" on your phone to get the 09:30 morning summary.
5. Give parents the link `t.me/your_bot`. They tap "Telefon raqamni yuborish"; the bot
   matches the number with the student's parent phone.
6. Switch debt reminders on in Sozlamalar → Umumiy sozlamalar when you are ready.

Locally the bot also works (it polls Telegram, no public address needed): put the token
into a `.env` next to `docker-compose.yml` and run `docker compose up`.

### Backups

The `backup` container runs `scripts/backup.sh` every night at 02:30 (Tashkent). It writes
to `BACKUP_DIR` (default `./backups` in the project folder):

- `daily/db_YYYY-MM-DD_HHMM.dump`: the whole database (`pg_dump` custom format, checked
  with `pg_restore --list` before it is kept),
- `daily/media_...tar.gz`: uploaded import files,
- `weekly/`: a copy of each Sunday's backup.

The newest 14 daily and 8 weekly sets are kept. Run a backup by hand:

```bash
scripts/backup.sh
```

Restore (replaces all data; asks you to type `RESTORE`, and makes a fresh backup first):

```bash
scripts/restore.sh backups/daily/db_2026-11-23_0230.dump backups/daily/media_2026-11-23_0230.tar.gz
```

**Backups on the same server are lost with the server.** Copy `BACKUP_DIR` somewhere else
regularly, for example to your own computer:

```bash
rsync -av user@server:/path/to/project/backups/ ./matematika-backups/
```

Automatic off-site copies need a storage service (possibly paid) and are not set up.

### Logs

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f web cron backup
```
