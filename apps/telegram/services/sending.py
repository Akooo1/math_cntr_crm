"""Outgoing messages: debt reminders to parents, the Direktor's morning summary."""

import datetime as dt
import logging
import time

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.billing import selectors as billing_selectors
from apps.core import dates, money, phone
from apps.core.permissions import require_perm
from apps.core.roles import Role
from apps.core.system_settings import get_setting
from apps.settings.selectors import receipt_details
from apps.staff import selectors as staff_selectors

from ..client import TelegramError, get_client
from ..models import Chat, Message
from .linking import disconnect

log = logging.getLogger(__name__)
PAUSE = 0.05  # stay far below Telegram's 30 messages per second


def _director():
    """Scheduled jobs read with the Direktor's scope (they see every branch)."""
    return (
        get_user_model().objects.filter(role=Role.DIRECTOR, is_active=True).order_by("pk").first()
    )


def deliver(chat: Chat, kind: str, text: str, student=None) -> Message:
    """Send one message and log it. A chat that blocked the bot is disconnected."""
    client = get_client()
    status, error = Message.Status.SENT, ""
    if client is None:
        status, error = Message.Status.FAILED, "TELEGRAM_BOT_TOKEN"
    else:
        try:
            client.send(chat.chat_id, text)
        except TelegramError as exc:
            status, error = Message.Status.FAILED, exc.description[:500]
            if exc.chat_gone:
                with transaction.atomic():
                    disconnect(chat)
    return Message.objects.create(
        chat=chat,
        kind=kind,
        student=student,
        text=text,
        status=status,
        error=error,
        sent_at=dates.now(),
    )


def _student_phones(student) -> list[str]:
    return [p for p in (student.parent_phone, student.phone, student.extra_phone) if p]


def debt_text(row) -> str:
    student = row["student"]
    info = receipt_details(student.branch)
    return _(
        "Hello! %(center)s.\n"
        "The payment for %(student)s is overdue by %(days)s days.\n"
        "Amount due: %(amount)s.\n"
        "Please pay at the center. Questions: %(phone)s"
    ) % {
        "center": info["center_name"],
        "student": student.full_name,
        "days": row["days"],
        "amount": money.format_som(row["overdue"]),
        "phone": phone.format_phone(info["phone"]) or info["branch_name"],
    }


def send_debt_reminders(*, force_actor=None) -> dict:
    """Daily at 10:00 (cron). `force_actor`: the Direktor pressed "send now" (runs even when
    switched off, still respects the repeat interval)."""
    if force_actor is not None:
        require_perm(force_actor, "telegram.manage")
    elif not get_setting("telegram.debt_reminders"):
        return {"sent": 0, "failed": 0, "skipped": 0, "off": True}
    reader = force_actor or _director()
    if reader is None:
        return {"sent": 0, "failed": 0, "skipped": 0}
    min_days = get_setting("telegram.debt_min_days")
    # By calendar day: a reminder sent on the 16th repeats on the 23rd whatever the seconds.
    last_allowed = dates.today() - dt.timedelta(days=get_setting("telegram.debt_repeat_days"))
    chats_by_phone = {}
    for chat in Chat.objects.filter(kind=Chat.Kind.PARENT, is_active=True):
        chats_by_phone.setdefault(chat.phone, []).append(chat)
    result = {"sent": 0, "failed": 0, "skipped": 0}
    for row in billing_selectors.debtors(reader):
        if row["days"] < min_days:
            continue
        student = row["student"]
        chats = {c.pk: c for p in _student_phones(student) for c in chats_by_phone.get(p, [])}
        if not chats:
            continue
        recent = Message.objects.filter(
            student=student,
            kind=Message.Kind.DEBT,
            status=Message.Status.SENT,
            sent_at__date__gt=last_allowed,
        ).exists()
        if recent:
            result["skipped"] += 1
            continue
        text = debt_text(row)
        for chat in chats.values():
            msg = deliver(chat, Message.Kind.DEBT, text, student)
            result["sent" if msg.status == Message.Status.SENT else "failed"] += 1
            time.sleep(PAUSE)
    return result


def summary_text(director, day: dt.date) -> str:
    board = staff_selectors.board(director, day)
    now = timezone.localtime(dates.now())
    on_time, late, missing, later = [], [], [], 0
    for r in board["rows"]:
        c, s = r["checkin"], r["schedule"]
        if r["status"] == "late":
            late.append(
                _("• %(name)s — %(time)s (%(m)s min late)")
                % {
                    "name": r["user"].full_name,
                    "time": f"{timezone.localtime(c.checked_in_at):%H:%M}",
                    "m": c.late_minutes,
                }
            )
        elif r["status"] in ("on_time",) or (c and r["status"] in ("day_off", "no_schedule")):
            on_time.append(r["user"].full_name)
        elif r["status"] == "not_yet":
            if s and s.start_time <= now.time():
                missing.append(
                    _("• %(name)s (work starts %(time)s)")
                    % {"name": r["user"].full_name, "time": f"{s.start_time:%H:%M}"}
                )
            else:
                later += 1
    lines = [
        _("Morning summary, %(date)s %(time)s")
        % {"date": dates.format_date(day), "time": f"{now:%H:%M}"},
        "",
        _("On time: %(n)s") % {"n": len(on_time)},
    ]
    if late:
        lines += ["", _("Late: %(n)s") % {"n": len(late)}, *late]
    if missing:
        lines += ["", _("Work has started, not here yet: %(n)s") % {"n": len(missing)}, *missing]
    if later:
        lines += ["", _("Work starts later today: %(n)s") % {"n": later}]
    return "\n".join(lines)


def _director_chats():
    return Chat.objects.filter(
        kind=Chat.Kind.STAFF, is_active=True, user__role=Role.DIRECTOR, user__is_active=True
    ).select_related("user")


def send_morning_summary(*, force_actor=None) -> dict:
    if force_actor is not None:
        require_perm(force_actor, "telegram.manage")
    result = {"sent": 0, "failed": 0}
    for chat in _director_chats():
        msg = deliver(chat, Message.Kind.SUMMARY, summary_text(chat.user, dates.today()))
        result["sent" if msg.status == Message.Status.SENT else "failed"] += 1
    return result


def send_test(*, actor) -> dict:
    require_perm(actor, "telegram.manage")
    result = {"sent": 0, "failed": 0}
    for chat in Chat.objects.filter(user=actor, is_active=True):
        msg = deliver(
            chat, Message.Kind.TEST, _("Test message from %(name)s.") % {"name": actor.full_name}
        )
        result["sent" if msg.status == Message.Status.SENT else "failed"] += 1
    return result
