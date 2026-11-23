"""Telegram reads."""

from django.core.cache import cache

from apps.core.permissions import require_perm
from apps.students import selectors as student_selectors

from .client import TelegramError, get_client
from .models import Chat, Message


def bot_username() -> str:
    """The bot's @username for t.me links (asked once a day). Empty when off or unreachable."""
    client = get_client()
    if client is None:
        return ""
    name = cache.get("telegram.bot_username")
    if name is None:
        try:
            name = client.call("getMe").get("username", "")
        except TelegramError:
            return ""
        cache.set("telegram.bot_username", name, 24 * 3600)
    return name


def overview(user) -> dict:
    require_perm(user, "telegram.manage")
    parents = list(Chat.objects.filter(kind=Chat.Kind.PARENT, is_active=True))
    students = {}
    for s in student_selectors.find_by_phones([c.phone for c in parents]):
        for p in (s.parent_phone, s.phone, s.extra_phone):
            if p:
                students.setdefault(p, []).append(s)
    return {
        "parents": [{"chat": c, "students": students.get(c.phone, [])} for c in parents],
        "staff": list(
            Chat.objects.filter(kind=Chat.Kind.STAFF, is_active=True).select_related("user")
        ),
        "my_chat": Chat.objects.filter(user=user, is_active=True).first(),
        "log": list(Message.objects.select_related("chat", "student")[:40]),
    }


def parent_connected(student) -> bool:
    phones = [p for p in (student.parent_phone, student.phone, student.extra_phone) if p]
    return Chat.objects.filter(kind=Chat.Kind.PARENT, is_active=True, phone__in=phones).exists()
