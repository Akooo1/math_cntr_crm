"""Messages the Direktor sends to parents from templates ("Farzandingiz kelmadi")."""

import datetime as dt
import time

from django.db import transaction

from apps.core import audit, dates, phone
from apps.core.permissions import require_perm
from apps.settings.selectors import receipt_details

from ..models import Chat, Message
from .sending import PAUSE, deliver

PLACEHOLDERS = ("oquvchi", "guruh", "sana", "filial", "telefon", "markaz")


def render(text: str, student, group_name: str = "", day: dt.date | None = None) -> str:
    """Replace only the known {placeholders}; any other braces stay as typed."""
    info = receipt_details(student.branch)
    values = {
        "oquvchi": student.full_name,
        "guruh": group_name,
        "sana": dates.format_date(day or dates.today()),
        "filial": student.branch.name,
        "telefon": phone.format_phone(info["phone"]) or "",
        "markaz": info["center_name"],
    }
    for key in PLACEHOLDERS:
        text = text.replace("{" + key + "}", values[key])
    return text.strip()


def parent_chats(student) -> list[Chat]:
    phones = [p for p in (student.parent_phone, student.phone, student.extra_phone) if p]
    return list(Chat.objects.filter(kind=Chat.Kind.PARENT, is_active=True, phone__in=phones))


def send_to_parents(*, actor, targets: list[tuple], text: str, day: dt.date | None = None):
    """targets: [(student, group name)]. Returns sent / failed counts and the students
    whose parents haven't connected the bot."""
    require_perm(actor, "telegram.send")
    result = {"sent": 0, "failed": 0, "no_parent": [], "students": 0}
    for student, group_name in targets:
        chats = parent_chats(student)
        if not chats:
            result["no_parent"].append(student)
            continue
        result["students"] += 1
        body = render(text, student, group_name, day)
        for chat in chats:
            msg = deliver(chat, Message.Kind.CUSTOM, body, student)
            result["sent" if msg.status == Message.Status.SENT else "failed"] += 1
            time.sleep(PAUSE)
    with transaction.atomic():
        audit.record(
            actor,
            "telegram.message.send",
            entity_type="telegram.message",
            entity_id="",
            after={
                "text": text[:500],
                "students": result["students"],
                "sent": result["sent"],
                "failed": result["failed"],
            },
        )
    return result
