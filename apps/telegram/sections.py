"""Sozlamalar → Telegram (Direktor)."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import has_perm
from apps.core.settings_panel import Column, SettingsSection
from apps.core.system_settings import get_setting

from . import selectors, services
from .client import get_client
from .forms import TemplateForm
from .models import Chat, Template


def _telegram_view(request, section):
    if request.method == "POST":
        action = request.POST.get("action")
        if not has_perm(request.user, "telegram.manage"):
            return redirect("settings:section_list", slug=section.slug)
        if action == "test":
            r = services.send_test(actor=request.user)
        elif action == "debts":
            r = services.send_debt_reminders(force_actor=request.user)
            messages.info(
                request,
                gettext(
                    "Sent: %(s)s. Not sent: %(f)s. Debtors: %(d)s, of them overdue less than "
                    "%(min)s days: %(e)s, parent not connected: %(n)s, already reminded "
                    "recently: %(k)s."
                )
                % {
                    "s": r["sent"],
                    "f": r["failed"],
                    "d": r["debtors"],
                    "min": get_setting("telegram.debt_min_days"),
                    "e": r["too_early"],
                    "n": r["no_parent"],
                    "k": r["skipped"],
                },
            )
            return redirect("settings:section_list", slug=section.slug)
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


class TemplateSection(SettingsSection):
    """Ready-made messages to parents. Used on "Ota-onalarga xabar"."""

    slug = "xabar-shablonlari"
    title = _("Message templates")
    description = _('Ready messages to parents, e.g. "Farzandingiz darsga kelmadi".')
    icon = "list"
    order = 97
    group = _("Notifications")
    model = Template
    form_class = TemplateForm
    audit_prefix = "telegram.template"
    columns = [
        Column(_("Name"), lambda t: t.title, primary=True),
        Column(_("Text"), lambda t: t.text[:80] + ("…" if len(t.text) > 80 else "")),
    ]
