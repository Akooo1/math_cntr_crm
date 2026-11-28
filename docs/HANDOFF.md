# Handoff: where things stand (read this first in a new chat)

Keep this file short and current: update it at the end of every round of changes.
Rules and conventions live in `CLAUDE.md`; every business decision lives in `docs/SPEC.md`.

## State (28.11.2026)

- **Live site**: Railway, deploys from `main` (services web / worker / bot, one Postgres with
  REAL data). `main` = SPEC §1–§23.
- **Work branch** `claude/sweet-keller-1by08z` = `main` + SPEC §24 (owner's round):
  To'lagan fix, registered-student check, reopening a cash day, the owner (Ega), several
  groups in one window, refund on leave, Maosh avansi + salaries from the Kassa, local
  `WEB_PORT`; and §25 (Ombor categories, deleting a never-used product, "Book" = Kitob,
  store sale rules respect reopened days). **Waiting for the owner to say "main".**
- New sessions get a new work branch name from the system; merge or rebase from
  `claude/sweet-keller-1by08z` first if it isn't on `main` yet.

## Waiting for the owner

1. Say "main" to release §24–§25. Before that: rehearse the upgrade (below), then fast-forward
   `main` to the work branch.
2. After the release: the owner makes themselves Ega (Sozlamalar → Foydalanuvchilar → own
   row → Ega). Until then every Direktor manages users.
3. Online demo with fake data: the owner decided it isn't needed. Don't build it.

## How we work (the owner's standing rules)

- Owner writes changes in short bullets, often mixed Uzbek/English. Collect, ask only real
  decisions (AskUserQuestion), then build. Money rules and data-model changes: always ask.
- "Take notes, don't start" means: investigate read-only, list causes, wait for "go".
- Never push to `main` without the owner's "main". Never touch live data. Demo data never
  reaches production (`config/settings/prod.py` drops `apps.demo`; a test checks it).
- Answers to the owner: plain language, direct, no padding; Uzbek when asked.

## Release checklist (each time before "main")

1. `uv run ruff check . && uv run ruff format --check .`, `uv run lint-imports`,
   `uv run python manage.py makemigrations --check --dry-run`, `npm run build:css` (commit
   the CSS), `scripts/i18n.sh` then `scripts/i18n.sh --check`, `uv run pytest`.
2. Rehearse on a copy: `git worktree add <tmp> origin/main`, create a database, `migrate` +
   `seed_demo` there with `config.settings.dev`, fingerprint every table (only the columns
   that existed before), run this branch's `migrate` with `config.settings.prod`, compare.
   Only Django's own tables (auth_permission, django_content_type, django_migrations) may
   change. Drop the database and the worktree after.
3. `git push origin HEAD:main` only as a fast-forward.

## Environment notes (cloud sessions)

- Postgres sometimes stops: `service postgresql start` (user/password `mm`/`mm`).
- Translations: after `scripts/i18n.sh`, fill empty `msgstr` in
  `locale/uz/LC_MESSAGES/django.po` (e.g. a small polib script: `uv run --with polib
  python ...`), then `uv run python manage.py compilemessages -l uz` and the check again.
  Use the glossary in `CLAUDE.md`. Money amounts in page text use U+202F between digit
  groups: in tests compare with `.replace(" ", " ")`.
- Owner's computer: macOS, Docker Desktop, runs `docker compose up` (dev settings, demo data;
  logins in `docs/demo.md`, password `demo12345`). Port 8000 busy there: `WEB_PORT=8001`.
