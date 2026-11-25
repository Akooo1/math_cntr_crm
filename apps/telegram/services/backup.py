"""Database backups sent to the Direktor's Telegram (docs/SPEC.md §18).

pg_dump (custom format) -> verified with pg_restore --list -> sendDocument to every active
Direktor chat. Used before every update that changes the database (scripts/entrypoint.sh)
and every night (deploy/crontab).
"""

import os
import subprocess
import tempfile

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import dates
from apps.core.roles import Role

from ..client import TelegramError, get_client
from ..models import Chat, Message

MAX_BYTES = 49 * 1024 * 1024  # Telegram bots may send files up to 50 MB


class BackupError(Exception):
    """The backup was not made or not delivered. The message says why, in plain words."""


def pending_migrations() -> tuple[bool, bool]:
    """(database already set up, update has database changes)."""
    executor = MigrationExecutor(connection)
    applied = executor.loader.applied_migrations
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return bool(applied), bool(plan)


def _pg_env() -> dict:
    db = settings.DATABASES["default"]
    return {
        **os.environ,
        "PGHOST": str(db["HOST"] or "localhost"),
        "PGPORT": str(db["PORT"] or "5432"),
        "PGUSER": str(db["USER"]),
        "PGPASSWORD": str(db["PASSWORD"]),
        "PGDATABASE": str(db["NAME"]),
    }


def dump() -> bytes:
    """The whole database as a pg_dump custom-format file, checked to be restorable."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "db.dump")
        env = _pg_env()
        made = subprocess.run(
            ["pg_dump", "--format=custom", "--compress=6", "--no-owner", f"--file={path}"],
            env=env,
            capture_output=True,
            text=True,
        )
        if made.returncode != 0:
            raise BackupError(f"pg_dump failed: {made.stderr.strip()[:500]}")
        check = subprocess.run(["pg_restore", "--list", path], capture_output=True, text=True)
        if check.returncode != 0:
            raise BackupError(f"the dump is not readable: {check.stderr.strip()[:500]}")
        with open(path, "rb") as fh:
            return fh.read()


def director_chats():
    return Chat.objects.filter(
        kind=Chat.Kind.STAFF, is_active=True, user__role=Role.DIRECTOR, user__is_active=True
    )


def configured() -> bool:
    return get_client() is not None and director_chats().exists()


def _size(n: int) -> str:
    return (
        f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB".replace(".", ",")
    )


def send_backup(*, reason: str) -> dict:
    """Make a backup and send it to every connected Direktor. Raises BackupError if no
    Direktor received it."""
    client = get_client()
    if client is None:
        raise BackupError("TELEGRAM_BOT_TOKEN is not set, so there is nowhere to send backups.")
    chats = list(director_chats())
    if not chats:
        raise BackupError(
            "No Direktor has connected Telegram (Sozlamalar -> Telegram -> Telegramimni ulash)."
        )
    content = dump()
    if len(content) > MAX_BYTES:
        raise BackupError(f"the backup is {_size(len(content))}, over Telegram's 50 MB limit.")
    now = timezone.localtime(dates.now())
    filename = f"matematika-{now:%Y-%m-%d_%H%M}.dump"
    why = _("before an update") if reason == "update" else _("nightly")
    caption = _(
        "Database backup (%(why)s): %(when)s, %(size)s.\n"
        "It contains all the center's data. Keep it, don't forward it. "
        "How to restore: docs/deploy-railway.md, section 6."
    ) % {"why": why, "when": f"{now:%d.%m.%Y %H:%M}", "size": _size(len(content))}
    delivered = 0
    errors = []
    for chat in chats:
        status, error = Message.Status.SENT, ""
        try:
            client.send_document(chat.chat_id, filename, content, caption)
            delivered += 1
        except TelegramError as exc:
            status, error = Message.Status.FAILED, exc.description[:500]
            errors.append(error)
        Message.objects.create(
            chat=chat,
            kind=Message.Kind.BACKUP,
            text=caption,
            status=status,
            error=error,
            sent_at=dates.now(),
        )
    if not delivered:
        raise BackupError(f"Telegram didn't accept the backup: {'; '.join(errors)}")
    return {"filename": filename, "bytes": len(content), "delivered": delivered}
