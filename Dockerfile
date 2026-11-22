# syntax=docker/dockerfile:1

# --- CSS build (Tailwind). Node exists only in this stage. ---------------------------
FROM node:22-alpine AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY static/src static/src
COPY templates templates
COPY apps apps
RUN npx tailwindcss -i static/src/app.css -o static/dist/app.css --minify

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
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && python manage.py compilemessages -l uz --ignore=node_modules \
    && useradd --system --uid 1000 app \
    && mkdir -p /app/media \
    && chown -R app /app/media
USER app
ENTRYPOINT ["scripts/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
