from django.utils.translation import gettext_lazy as _

from apps.core.audit_display import register_labels as register_audit_labels
from apps.core.permissions import register_permission
from apps.core.roles import Role
from apps.core.settings_panel import register_section
from apps.core.system_settings import SettingDef, register_setting
from apps.students import services as student_services

register_permission("telegram.manage", _("Manage the Telegram bot"), {Role.DIRECTOR})
register_permission(
    "telegram.view", _("See Telegram connections"), {Role.DIRECTOR, Role.BRANCH_ADMIN}
)

register_setting(
    SettingDef(
        key="telegram.debt_reminders",
        label=_("Debt reminders in Telegram"),
        help_text=_("Every day at 10:00 to connected parents of students with overdue debt."),
        default=0,
        choices=((0, _("Off")), (1, _("On"))),
        order=80,
    )
)
register_setting(
    SettingDef(
        key="telegram.debt_min_days",
        label=_("Remind after (days overdue)"),
        default=3,
        min_value=1,
        max_value=60,
        order=81,
    )
)
register_setting(
    SettingDef(
        key="telegram.debt_repeat_days",
        label=_("Repeat the reminder every (days)"),
        default=7,
        min_value=1,
        max_value=60,
        order=82,
    )
)

register_audit_labels(
    {
        "chat_id": _("Telegram chat"),
        "tg_name": _("Telegram name"),
        "connected_at": _("Connected at"),
        "disconnected_at": _("Disconnected at"),
    }
)


def _panel(request, student):
    from . import selectors

    return {"connected": selectors.parent_connected(student)}


def _register():
    from .sections import TelegramSection

    register_section(TelegramSection())
    student_services.register_profile_panel(
        student_services.ProfilePanel(
            key="telegram",
            template="telegram/panel_student.html",
            permission="telegram.view",
            context=_panel,
            order=30,
        )
    )


_register()
