"""Database backups to the Direktor's Telegram (docs/SPEC.md §18)."""

import io
import json
import subprocess

import pytest
from django.core.management import CommandError, call_command

from apps.telegram import client as tg
from apps.telegram import services
from apps.telegram.client import TelegramError
from apps.telegram.models import Message
from apps.telegram.services import backup

pytestmark = pytest.mark.django_db


class FakeTelegram:
    def __init__(self):
        self.documents = []
        self.fail = None

    def call(self, method, **params):
        return True

    def send(self, chat_id, text, **extra):
        return {}

    def send_document(self, chat_id, filename, content, caption=""):
        if self.fail:
            raise self.fail
        self.documents.append({"chat_id": chat_id, "filename": filename, "content": content})
        return {}


@pytest.fixture
def bot(settings):
    settings.TELEGRAM_BOT_TOKEN = "123:TEST"
    fake = FakeTelegram()
    tg.set_client(fake)
    yield fake
    tg.set_client(None)


@pytest.fixture
def director_chat(bot, director):
    token = services.link_token(director)
    msg = {"chat": {"id": 500, "type": "private"}, "from": {"id": 500}, "text": f"/start {token}"}
    services.handle_update({"update_id": 1, "message": msg})


def test_backup_is_a_restorable_dump_sent_to_the_direktor(bot, director_chat, tmp_path):
    result = backup.send_backup(reason="update")
    doc = bot.documents[-1]
    assert doc["chat_id"] == 500 and doc["filename"].endswith(".dump")
    assert doc["content"][:5] == b"PGDMP" and result["delivered"] == 1
    path = tmp_path / "x.dump"
    path.write_bytes(doc["content"])
    listing = subprocess.run(["pg_restore", "--list", str(path)], capture_output=True, text=True)
    assert listing.returncode == 0 and "billing_payment" in listing.stdout
    assert Message.objects.filter(kind="backup", status="sent").exists()


def test_refuses_when_nobody_can_receive_it(bot, settings):
    with pytest.raises(backup.BackupError, match="No Direktor"):
        backup.send_backup(reason="nightly")
    settings.TELEGRAM_BOT_TOKEN = ""
    tg.set_client(None)
    with pytest.raises(backup.BackupError, match="TELEGRAM_BOT_TOKEN"):
        backup.send_backup(reason="nightly")


def test_telegram_failure_is_an_error_and_logged(bot, director_chat):
    bot.fail = TelegramError("Request Entity Too Large", 413)
    with pytest.raises(backup.BackupError, match="Telegram"):
        backup.send_backup(reason="update")
    assert Message.objects.get(kind="backup").status == "failed"


def test_too_big_for_telegram(bot, director_chat, monkeypatch):
    monkeypatch.setattr(backup, "MAX_BYTES", 10)
    with pytest.raises(backup.BackupError, match="50 MB"):
        backup.send_backup(reason="nightly")
    assert bot.documents == []


def test_before_migrate_skips_when_the_update_has_no_database_changes(bot, director_chat, capsys):
    call_command("backup_to_telegram", "--before-migrate")
    assert "no database changes" in capsys.readouterr().out and bot.documents == []


def test_before_migrate_backs_up_when_changes_are_pending(bot, director_chat, monkeypatch):
    monkeypatch.setattr(backup, "pending_migrations", lambda: (True, True))
    call_command("backup_to_telegram", "--before-migrate")
    assert len(bot.documents) == 1


def test_failed_backup_stops_the_command(bot, monkeypatch):
    monkeypatch.setattr(backup, "pending_migrations", lambda: (True, True))
    with pytest.raises(CommandError, match="backup FAILED"):
        call_command("backup_to_telegram", "--before-migrate")


def test_nightly_skips_quietly_until_configured(settings, capsys):
    settings.TELEGRAM_BOT_TOKEN = ""
    tg.set_client(None)
    call_command("backup_to_telegram", "--nightly-if-configured")
    assert "skipped" in capsys.readouterr().out


def test_client_uploads_multipart(monkeypatch):
    sent = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        sent["url"], sent["type"], sent["body"] = (
            req.full_url,
            req.headers["Content-type"],
            req.data,
        )
        return Resp(json.dumps({"ok": True, "result": {}}).encode())

    monkeypatch.setattr(tg.urllib.request, "urlopen", fake_urlopen)
    tg.TelegramClient("123:ABC").send_document(7, "a.dump", b"PGDMP\x00\x01", "zaxira")
    assert sent["url"].endswith("/sendDocument") and "multipart/form-data" in sent["type"]
    assert b'filename="a.dump"' in sent["body"] and b"PGDMP\x00\x01" in sent["body"]
    assert b"zaxira" in sent["body"] and b'name="chat_id"\r\n\r\n7' in sent["body"]
