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


def test_without_railway_variables_nothing_changes():
    s = _settings_in_subprocess(DATABASE_URL="", RAILWAY_PUBLIC_DOMAIN="")
    assert "healthcheck.railway.app" not in s["hosts"]


@pytest.mark.django_db
def test_first_direktor_from_variables_only_once():
    args = ["--if-none", "--must-change", "--phone", "90 777 00 01", "--name", "Birinchi"]
    call_command("create_director", *args, "--password", "Railway!2026x")
    user = User.objects.get(role=Role.DIRECTOR)
    assert user.must_change_password and user.phone == "+998907770001"
    call_command("create_director", *args, "--password", "Other!2026xx")  # second start
    assert User.objects.filter(role=Role.DIRECTOR).count() == 1
    assert user.check_password("Railway!2026x")
