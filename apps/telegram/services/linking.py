"""Connecting chats: parents share their phone; staff open a signed one-day link."""

import datetime as dt
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.translation import gettext as _

from apps.core import audit, dates, phone
from apps.students import selectors as student_selectors

from ..client import TelegramError, get_client
from ..models import Chat, Message
from . import parent_menu

log = logging.getLogger(__name__)


def link_token(user, day: dt.date | None = None) -> str:
    """ "<user id>_<20 hex>", valid today and tomorrow. Fits Telegram's /start parameter
    (64 characters of A-Z a-z 0-9 _ -)."""
    day = day or dates.today()
    sig = salted_hmac("telegram-link", f"{user.pk}:{day.isoformat()}").hexdigest()[:20]
    return f"{user.pk}_{sig}"


def user_for_token(token: str):
    try:
        pk = int(token.split("_", 1)[0])
    except (ValueError, AttributeError):
        return None
    user = get_user_model().objects.filter(pk=pk, is_active=True).first()
    if user is None:
        return None
    today = dates.today()
    for day in (today, today - dt.timedelta(days=1)):
        if constant_time_compare(token, link_token(user, day)):
            return user
    return None


def _reply(chat_id: int, text: str, chat: Chat | None = None, **extra) -> None:
    client = get_client()
    if client is None:
        return
    try:
        client.send(chat_id, text, **extra)
    except TelegramError as exc:
        log.warning("telegram reply to %s failed: %s", chat_id, exc)
        return
    if chat is not None:
        Message.objects.create(
            chat=chat, kind=Message.Kind.REPLY, text=text, status="sent", sent_at=dates.now()
        )


def _name(sender: dict) -> str:
    parts = [sender.get("first_name", ""), sender.get("last_name", "")]
    name = " ".join(p for p in parts if p).strip()
    if sender.get("username"):
        name = f"{name} (@{sender['username']})".strip()
    return name[:150]


def _ask_phone(chat_id: int) -> None:
    _reply(
        chat_id,
        _(
            "Hello! This is the bot of %(center)s. Parents: tap the button below to share "
            "your phone number. We will send you payment reminders for your child."
        )
        % {"center": _center_name()},
        reply_markup={
            "keyboard": [[{"text": _("Share phone number"), "request_contact": True}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        },
    )


def _center_name() -> str:
    from apps.settings.selectors import center_info

    return center_info().center_name


def _upsert(chat_id: int, **fields) -> Chat:
    chat = Chat.objects.filter(chat_id=chat_id).first()
    before = audit.snapshot(chat)
    if chat is None:
        chat = Chat(chat_id=chat_id)
    for key, value in fields.items():
        setattr(chat, key, value)
    chat.is_active, chat.disconnected_at, chat.connected_at = True, None, dates.now()
    chat.save()
    audit.record(None, "telegram.chat.connect", chat, before=before, after=audit.snapshot(chat))
    return chat


def link_parent(chat_id: int, contact: dict, sender: dict) -> Chat | None:
    """The person shared a contact. Only their own number counts."""
    if contact.get("user_id") != sender.get("id"):
        _reply(chat_id, _("Please share your own number with the button below."))
        _ask_phone(chat_id)
        return None
    raw = contact.get("phone_number", "")
    number = phone.normalize_or_none(raw if raw.startswith("+") else f"+{raw}")
    students = list(student_selectors.find_by_phones([number])) if number else []
    if not students:
        _reply(
            chat_id,
            _(
                "We couldn't find a student with this phone number. Please ask the "
                "center's administrator to add it."
            ),
            reply_markup={"remove_keyboard": True},
        )
        return None
    with transaction.atomic():
        chat = _upsert(
            chat_id, kind=Chat.Kind.PARENT, phone=number, user=None, tg_name=_name(sender)
        )
    names = ", ".join(sorted({s.full_name for s in students}))
    _reply(
        chat_id,
        _("Connected. You will get reminders about: %(names)s. Send /stop to disconnect.")
        % {"names": names}
        + "\n\n"
        + _("Use the menu below to see the balance, attendance, payments and schedule."),
        chat,
        reply_markup=parent_menu.keyboard(),
    )
    return chat


def link_staff(chat_id: int, token: str, sender: dict) -> Chat | None:
    user = user_for_token(token)
    if user is None:
        _reply(chat_id, _("This link has expired. Open a new one in Sozlamalar → Telegram."))
        return None
    with transaction.atomic():
        chat = _upsert(chat_id, kind=Chat.Kind.STAFF, user=user, phone="", tg_name=_name(sender))
    _reply(
        chat_id,
        _("Connected, %(name)s. Reports will come here. Send /stop to disconnect.")
        % {"name": user.full_name},
        chat,
    )
    return chat


def disconnect(chat: Chat, actor=None) -> None:
    before = audit.snapshot(chat)
    chat.is_active, chat.disconnected_at = False, dates.now()
    chat.save(update_fields=["is_active", "disconnected_at"])
    audit.record(actor, "telegram.chat.disconnect", chat, before=before, after=audit.snapshot(chat))


def handle_update(update: dict) -> None:
    """One update from getUpdates. Only private text and contact messages matter."""
    msg = update.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if not chat_id or (msg.get("chat") or {}).get("type") != "private":
        return
    sender = msg.get("from") or {}
    text = (msg.get("text") or "").strip()
    if msg.get("contact"):
        link_parent(chat_id, msg["contact"], sender)
    elif text.startswith("/start"):
        param = text.split(maxsplit=1)[1].strip() if " " in text else ""
        parent = Chat.objects.filter(chat_id=chat_id, kind=Chat.Kind.PARENT, is_active=True).first()
        if param:
            link_staff(chat_id, param, sender)
        elif parent is not None:  # already connected: just show the menu
            _reply(
                chat_id,
                _("Choose from the menu below."),
                parent,
                reply_markup=parent_menu.keyboard(),
            )
        else:
            _ask_phone(chat_id)
    elif text == "/stop":
        chat = Chat.objects.filter(chat_id=chat_id, is_active=True).first()
        if chat:
            with transaction.atomic():
                disconnect(chat)
        _reply(
            chat_id,
            _("Disconnected. Send /start to connect again."),
            reply_markup={"remove_keyboard": True},
        )
    else:
        parent = Chat.objects.filter(chat_id=chat_id, kind=Chat.Kind.PARENT, is_active=True).first()
        if parent is None:
            _ask_phone(chat_id)
            return
        key = parent_menu.which(text)
        if key is None:  # /menu or anything else: show the menu again
            _reply(
                chat_id,
                _("Choose from the menu below."),
                parent,
                reply_markup=parent_menu.keyboard(),
            )
        else:
            _reply(
                chat_id,
                parent_menu.answer(parent, key),
                parent,
                reply_markup=parent_menu.keyboard(),
            )
