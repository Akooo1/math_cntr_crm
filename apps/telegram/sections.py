"""Sozlamalar → Telegram (Direktor)."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import has_perm
from apps.core.settings_panel import SettingsSection

from . import selectors, services
from .client import get_client
from .models import Chat


def _telegram_view(request, section):
    if request.method == "POST":
        action = request.POST.get("action")
        if not has_perm(request.user, "telegram.manage"):
            return redirect("settings:section_list", slug=section.slug)
        if action == "test":
            r = services.send_test(actor=request.user)
        elif action == "debts":
            r = services.send_debt_reminders(force_actor=request.user)
        elif action == "summary":
            r = services.send_morning_summary(force_actor=request.user)
        else:
            return redirect("settings:section_list", slug=section.slug)
        messages.info(
            request,
            gettext("Sent: %(s)s. Not sent: %(f)s.") % {"s": r["sent"], "f": r["failed"]},
        )
        return redirect("settings:section_list", slug=section.slug)
    username = selectors.bot_username()
    link = ""
    if username:
        link = f"https://t.me/{username}?start={services.link_token(request.user)}"
    return render(
        request,
        "telegram/settings.html",
        {
            "section": section,
            "configured": get_client() is not None,
            "username": username,
            "my_link": link,
            **selectors.overview(request.user),
        },
    )


class TelegramSection(SettingsSection):
    slug = "telegram"
    title = _("Telegram bot")
    description = _("Debt reminders to parents, the morning summary, connections and log.")
    icon = "send"
    order = 96
    group = _("Notifications")
    model = Chat
    custom_view = staticmethod(_telegram_view)
    allow_create = False
    allow_edit = False
    allow_toggle_active = False
