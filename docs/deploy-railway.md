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
   TELEGRAM_BOT_TOKEN=${{bot.TELEGRAM_BOT_TOKEN}}
   ```

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
   TELEGRAM_BOT_TOKEN=<token from @BotFather>
   ```

4. Also add `TELEGRAM_BOT_TOKEN=${{bot.TELEGRAM_BOT_TOKEN}}` to `web`, so Sozlamalar →
   Telegram can show the bot and send test messages.
5. Logs: `Telegram bot is running.` Then follow README → "Telegram bot" from step 4.

## 6. Backups

- **Postgres service → Backups:** turn on a **daily** schedule (and weekly if offered).
  Restores happen from the same tab.
- Railway keeps backups in the same place as the database, and deleting the volume deletes
  them. Once a month, keep a copy on your own computer too. Turn on **Postgres →
  Settings → Networking → TCP Proxy**, copy `DATABASE_PUBLIC_URL` from its variables, then:

  ```bash
  docker run --rm postgres:17-alpine pg_dump "PASTE_DATABASE_PUBLIC_URL" -Fc > matematika.dump
  ```

  Turn the TCP proxy off again afterwards: while it is on, the database is reachable from
  the internet (password protected).

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
| Deploy fails at "healthcheck" | `web` logs: usually `DJANGO_SECRET_KEY` or `DATABASE_URL` missing |
| "Bad Request (400)" in the browser | you use a custom domain: step 8 variables |
| "CSRF verification failed" when logging in | same as above |
| Import upload fails with "permission denied" | the volume and `RAILWAY_RUN_UID=0` (step 2.4) |
| No morning summary / reminders | `worker` logs at 09:30 / 10:00 Tashkent; `TELEGRAM_BOT_TOKEN` on `worker` |
