# Deploying on Railway

Railway runs the same Docker image as Docker Compose, split into services:

| Railway service | What it runs | Config file |
|---|---|---|
| **Postgres** | Railway's PostgreSQL database | (Railway template) |
| **web** | the website (gunicorn); migrates the database on every deploy | `railway.json` |
| **worker** | scheduled jobs on Tashkent time: monthly charges 00:10, lesson calendars 00:20, morning summary 09:30, debt reminders 10:00, session cleanup 03:40 | `deploy/railway/worker.json` |
| **bot** | the Telegram bot (idles until a token is set) | `deploy/railway/bot.json` |

Caddy and the backup container are not used on Railway: Railway provides HTTPS and has its
own database backups.

**Cost.** The Hobby plan is $5 a month and includes $5 of usage; usage above that is billed
on top (RAM $10 per GB per month, CPU $20 per vCPU per month, volumes $0.15 per GB). These
four services need about 0.6–0.8 GB of RAM in total, so expect **roughly $7–12 a month**.
That is an estimate, not a quote: set a usage limit in Railway → Account → Usage so a
surprise can't happen.

**Clean start.** Railway never loads demo data: the database starts with only the defaults
the system needs (payment methods, lead stages, editable lead sources and refusal reasons,
the center name) plus the Direktor from step 3.

**Data location.** Railway's servers are outside Uzbekistan. See docs/SPEC.md (hosting)
about the personal-data localization law before you load real student data.

---

## 1. Create the project and the database

1. Sign in at railway.com with GitHub and choose the **Hobby** plan.
2. **New Project → Deploy PostgreSQL.** Railway creates a service called `Postgres`.
3. If Railway asks for a region, pick the one closest to Tashkent that is offered
   (Europe is usually closest).

## 2. The `web` service

1. In the project: **+ Create → GitHub Repo → `akooo1/math_cntr_crm`.**
2. Open the new service → **Settings**:
   - **Service name:** `web`.
   - **Source → Branch:** `main`.
   - **Networking → Generate Domain.** You get an address like
     `matematika-production.up.railway.app`. The app trusts it automatically.
3. **Variables** (Raw Editor, paste and fill in):

   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   DJANGO_SECRET_KEY=<50 random characters>
   TZ=Asia/Tashkent
   WEB_CONCURRENCY=2
   RAILWAY_RUN_UID=0
   DIRECTOR_PHONE=+998 90 123 45 67
   DIRECTOR_NAME=Ism Familiya
   DIRECTOR_PASSWORD=<a temporary password, at least 8 characters>
   ```

   Make the secret key on your computer, for example:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

4. **Volume:** right-click the `web` service → **Attach Volume**, mount path `/app/media`
   (uploaded Excel import files). Railway mounts volumes owned by root; with
   `RAILWAY_RUN_UID=0` the container starts as root only to hand that folder to the app
   user, and the app itself then runs as that normal user (`scripts/entrypoint.sh`).
5. Railway builds and deploys. The first build takes about 5 minutes. The deploy is healthy
   when `/healthz` answers.

## 3. First login

1. Open the domain from step 2. Log in with `DIRECTOR_PHONE` and `DIRECTOR_PASSWORD`.
2. The app asks for a new password at once. Choose a strong one.
3. **Delete `DIRECTOR_PASSWORD`** (and the other two `DIRECTOR_` variables) from the `web`
   variables. They are only read when no Direktor exists, but they shouldn't stay there.
4. In Sozlamalar set up branches, rooms, courses, prices and users, or import from Excel
   (Import).

## 4. The `worker` service (scheduled jobs)

1. **+ Create → GitHub Repo → the same repository** again. Name it `worker`, same branch.
2. **Settings → Config-as-code → Railway Config File:** `deploy/railway/worker.json`.
3. **Variables:**

   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   DJANGO_SECRET_KEY=${{web.DJANGO_SECRET_KEY}}
   TZ=Asia/Tashkent
   SKIP_MIGRATE=1
   PROCESS=worker
   TELEGRAM_BOT_TOKEN=${{bot.TELEGRAM_BOT_TOKEN}}
   ```

   `PROCESS` tells the image what to run, so the service works even if Railway ignores the
   config file (a service named `worker` also works without it).

4. No domain. In its logs you should see `read crontab: /app/deploy/crontab`.

## 5. The `bot` service (Telegram)

1. **+ Create → GitHub Repo → the same repository.** Name it `bot`, same branch.
2. **Railway Config File:** `deploy/railway/bot.json`.
3. **Variables:**

   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   DJANGO_SECRET_KEY=${{web.DJANGO_SECRET_KEY}}
   TZ=Asia/Tashkent
   SKIP_MIGRATE=1
   PROCESS=bot
   TELEGRAM_BOT_TOKEN=<token from @BotFather>
   ```

4. Also add `TELEGRAM_BOT_TOKEN=${{bot.TELEGRAM_BOT_TOKEN}}` to `web`, so Sozlamalar →
   Telegram can show the bot and send test messages.
5. Logs: `Process: bot`, then `Telegram bot is running.` Then follow README → "Telegram bot" from step 4.

## 6. Backups

**Automatic, to your Telegram.** The system sends a full copy of the database (a `.dump`
file) to every Direktor who connected Telegram (Sozlamalar → Telegram → Telegramimni ulash):

- **before every update that changes the database.** `web` makes the copy first; if the copy
  can't be made or delivered, the update stops, the database is not touched and the previous
  version keeps running. The `web` log says why. Fix it (usually: connect your Telegram) and
  redeploy, or set `BACKUP_BEFORE_MIGRATE=0` on `web` to skip the backup once;
- **every night at 02:30** (the `worker` service), as long as the bot token is set and a
  Direktor is connected.

Railway's own Backups tab is not available on the Hobby plan; these files are your backups.
Keep them; they contain all student and payment data.

**A copy by hand**, any time: on your computer, in a folder, with Docker running. Copy
`DATABASE_PUBLIC_URL` from Postgres → Variables (turn on Settings → Networking → TCP Proxy if
it's missing):

```bash
docker run --rm -v "${PWD}:/backup" postgres:18-alpine pg_dump "PASTE_DATABASE_PUBLIC_URL" -Fc -f /backup/matematika.dump
```

In Command Prompt write `%cd%` instead of `${PWD}`. Check a copy is readable (prints a long
list of tables):

```bash
docker run --rm -v "${PWD}:/backup" postgres:18-alpine pg_restore --list /backup/matematika.dump
```

**Restore** a copy (from Telegram or by hand): put the `.dump` file in a folder, stop `web`,
`worker` and `bot` in Railway so nothing writes meanwhile, then:

```bash
docker run --rm -v "${PWD}:/backup" postgres:18-alpine pg_restore --clean --if-exists --no-owner -d "PASTE_DATABASE_PUBLIC_URL" /backup/matematika-2026-11-25_0230.dump
```

Start the three services again afterwards.

## 7. Updates

Every push to the selected branch redeploys all three services. `web` applies database
migrations on start; `worker` and `bot` don't. For a minute during a deploy the worker or
bot can run on the new code before `web` finished migrating; the jobs are safe to repeat.

## 8. Your own domain (optional)

1. `web` → Settings → Networking → **Custom Domain**, e.g. `crm.example.uz`. Railway shows a
   CNAME record; add it at your domain registrar.
2. Add to `web` variables:

   ```
   DJANGO_ALLOWED_HOSTS=crm.example.uz
   DJANGO_CSRF_TRUSTED_ORIGINS=https://crm.example.uz
   ```

## If something goes wrong

| Symptom | Check |
|---|---|
| `bot` or `worker` logs show `Starting gunicorn` | it runs the website: add `PROCESS=bot` / `PROCESS=worker` to its variables |
| Deploy fails at "healthcheck" | `web` logs: usually `DJANGO_SECRET_KEY` or `DATABASE_URL` missing |
| "Bad Request (400)" in the browser | you use a custom domain: step 8 variables |
| "CSRF verification failed" when logging in | same as above |
| Import upload fails with "permission denied" | the volume and `RAILWAY_RUN_UID=0` (step 2.4) |
| No morning summary / reminders | `worker` logs at 09:30 / 10:00 Tashkent; `TELEGRAM_BOT_TOKEN` on `worker` |
