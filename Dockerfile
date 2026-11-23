# syntax=docker/dockerfile:1

# --- CSS build (Tailwind). Node exists only in this stage. ---------------------------
FROM node:22-alpine AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY assets assets
COPY templates templates
COPY apps apps
RUN npx tailwindcss -i assets/app.css -o static/dist/app.css --minify

# --- Python base -----------------------------------------------------------------------
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"
RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext \
    && apt-get clean \
    && pip install --no-cache-dir uv==0.11.32
# supercronic runs the scheduled jobs (deploy/crontab) in the cron container.
ARG TARGETARCH=amd64
ARG SUPERCRONIC_VERSION=v0.2.33
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) sum=71b0d58cc53f6bd72cf2f293e09e294b79c666d8 ;; \
      arm64) sum=e0f0c06ebc5627e43b25475711e694450489ab00 ;; \
      *) echo "unsupported arch $TARGETARCH"; exit 1 ;; \
    esac; \
    python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/usr/local/bin/supercronic')" \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}"; \
    echo "$sum  /usr/local/bin/supercronic" | sha1sum -c -; \
    chmod +x /usr/local/bin/supercronic
WORKDIR /app
COPY pyproject.toml uv.lock ./

# --- Development image (docker compose up) ----------------------------------------------
FROM base AS dev
RUN uv sync --frozen
COPY . .
COPY --from=assets /build/static/dist static/dist
ENV DJANGO_SETTINGS_MODULE=config.settings.dev
ENTRYPOINT ["scripts/entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# --- Production image --------------------------------------------------------------------
FROM base AS prod
RUN uv sync --frozen --no-dev
COPY . .
COPY --from=assets /build/static/dist static/dist
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
RUN export DJANGO_SECRET_KEY=build-only \
    && python manage.py collectstatic --noinput \
    && python manage.py compilemessages -l uz --ignore=node_modules \
    && useradd --system --uid 1000 app \
    && mkdir -p /app/media \
    && chown -R app /app/media
USER app
ENTRYPOINT ["scripts/entrypoint.sh"]
# PORT and WEB_CONCURRENCY come from the host (Railway sets PORT); defaults for Compose.
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-3} --access-logfile -"]
