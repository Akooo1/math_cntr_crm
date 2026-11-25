"""Deployment glue: Railway variables and the first Direktor (docs/deploy-railway.md)."""

import json
import os
import subprocess
import sys

import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.core.roles import Role


def _settings_in_subprocess(**env):
    code = (
        "import json, django; from django.conf import settings; django.setup(); "
        "d = settings.DATABASES['default']; "
        "print(json.dumps({k: d[k] for k in ('NAME','USER','PASSWORD','HOST','PORT')} | "
        "{'hosts': settings.ALLOWED_HOSTS, 'csrf': settings.CSRF_TRUSTED_ORIGINS}))"
    )
    full_env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        "DJANGO_SECRET_KEY": "x" * 50,
        **env,
    }
    out = subprocess.run(
        [sys.executable, "-c", code], env=full_env, capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_database_url_and_railway_domain():
    s = _settings_in_subprocess(
        DATABASE_URL="postgresql://rail:p%40ss%3Aw%2Frd@postgres.railway.internal:5433/railway",
        RAILWAY_PUBLIC_DOMAIN="markaz.up.railway.app",
    )
    assert (s["NAME"], s["USER"], s["PASSWORD"]) == ("railway", "rail", "p@ss:w/rd")
    assert (s["HOST"], s["PORT"]) == ("postgres.railway.internal", "5433")
    assert "markaz.up.railway.app" in s["hosts"] and "healthcheck.railway.app" in s["hosts"]
    assert "https://markaz.up.railway.app" in s["csrf"]


def test_railway_domain_generated_after_start():
    # Domain made after the deploy: RAILWAY_PUBLIC_DOMAIN missing, but Railway's ids are set.
    s = _settings_in_subprocess(RAILWAY_PROJECT_ID="p-123", RAILWAY_PUBLIC_DOMAIN="")
    assert ".up.railway.app" in s["hosts"] and "https://*.up.railway.app" in s["csrf"]


def test_without_railway_variables_nothing_changes():
    s = _settings_in_subprocess(
        DATABASE_URL="",
        RAILWAY_PUBLIC_DOMAIN="",
        RAILWAY_PROJECT_ID="",
        RAILWAY_ENVIRONMENT_NAME="",
    )
    assert "healthcheck.railway.app" not in s["hosts"] and ".up.railway.app" not in s["hosts"]


@pytest.mark.django_db
def test_first_direktor_from_variables_only_once():
    args = ["--if-none", "--must-change", "--phone", "90 777 00 01", "--name", "Birinchi"]
    call_command("create_director", *args, "--password", "Railway!2026x")
    user = User.objects.get(role=Role.DIRECTOR)
    assert user.must_change_password and user.phone == "+998907770001"
    call_command("create_director", *args, "--password", "Other!2026xx")  # second start
    assert User.objects.filter(role=Role.DIRECTOR).count() == 1
    assert user.check_password("Railway!2026x")


# --- which process a container runs (scripts/start.sh) ---------------------------------------


def _process(**env):
    clean = {k: v for k, v in os.environ.items() if k not in ("PROCESS", "RAILWAY_SERVICE_NAME")}
    out = subprocess.run(
        ["sh", "scripts/process.sh"], env={**clean, **env}, capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "web"),
        ({"RAILWAY_SERVICE_NAME": "web"}, "web"),
        ({"RAILWAY_SERVICE_NAME": "bot"}, "bot"),
        ({"RAILWAY_SERVICE_NAME": "Telegram-Bot"}, "bot"),
        ({"RAILWAY_SERVICE_NAME": "worker"}, "worker"),
        ({"RAILWAY_SERVICE_NAME": "bot", "PROCESS": "worker"}, "worker"),  # PROCESS wins
        ({"PROCESS": "bot"}, "bot"),
        ({"RAILWAY_SERVICE_NAME": "matematika"}, "web"),
    ],
)
def test_process_from_variable_or_railway_service_name(env, expected):
    assert _process(**env) == expected


def test_only_the_website_migrates():
    text = open("scripts/entrypoint.sh").read()
    assert '[ "$process" = "web" ]' in text and "migrate --noinput" in text


def test_image_default_command_picks_the_process():
    text = open("Dockerfile").read()
    assert 'CMD ["scripts/start.sh"]' in text
    start = open("scripts/start.sh").read()
    assert "telegram_bot" in start and "supercronic" in start and "gunicorn" in start


def test_health_server_answers_ok(tmp_path):
    import socket
    import time
    import urllib.request

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    subprocess.run(
        ["sh", "scripts/health_server.sh"], env={**os.environ, "PORT": str(port)}, check=True
    )
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
                    assert (r.status, r.read()) == (200, b"ok")
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("health server did not answer")
    finally:
        subprocess.run(["pkill", "-f", "ThreadingHTTPServer"], check=False)
