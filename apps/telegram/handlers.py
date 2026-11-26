"""Reacting to other modules' events."""

from django.db import transaction

from apps.alerts.events import AlertCreated
from apps.core.events import subscribe


@subscribe(AlertCreated)
def lead_warning_to_manager(event: AlertCreated) -> None:
    """A new lead was not contacted in time: tell its manager in Telegram (if connected and
    the Direktor left this on). Sent after the task is saved."""
    if event.kind != "lead" or not event.assigned_to_id:
        return
    transaction.on_commit(lambda: _send_lead_warning(event.task_id, event.assigned_to_id))


def _send_lead_warning(task_id: int, user_id: int) -> None:
    from django.conf import settings
    from django.utils import translation
    from django.utils.translation import gettext as _

    from apps.alerts.models import Task
    from apps.core import phone
    from apps.core.system_settings import get_setting

    from .models import Chat, Message
    from .services.sending import deliver

    if not get_setting("alerts.lead_telegram"):
        return
    chat = Chat.objects.filter(kind=Chat.Kind.STAFF, user_id=user_id, is_active=True).first()
    task = Task.objects.select_related("lead").filter(pk=task_id).first()
    if chat is None or task is None:
        return
    with translation.override(settings.LANGUAGE_CODE):
        lead = task.lead
        text = _("New lead not contacted yet: %(name)s, %(phone)s. Please call now.") % {
            "name": lead.full_name or "—",
            "phone": phone.format_phone(lead.phone) if lead.phone else "—",
        }
        deliver(chat, Message.Kind.ALERT, text)
