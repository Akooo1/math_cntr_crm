from django.utils.translation import gettext_lazy as _

from apps.core.permissions import register_permission
from apps.core.registry import DashboardWidget, NavItem, registry
from apps.core.roles import Role
from apps.core.system_settings import SettingDef, register_setting

D, A, M, T = Role.DIRECTOR, Role.BRANCH_ADMIN, Role.SALES_MANAGER, Role.TEACHER

register_permission("alerts.view", _("See and close warnings"), {D, A, M, T})

registry.add_nav(
    NavItem(
        key="alerts",
        label=_("Warnings"),
        url_name="alerts:list",
        icon="alert",
        permission="alerts.view",
        order=15,
        mobile_priority=45,
        active_prefix="/ogohlantirishlar/",
    )
)

# Rules the Direktor edits in Sozlamalar -> Umumiy sozlamalar. 0 switches a rule off.
for definition in (
    SettingDef(
        key="alerts.absence_streak",
        label=_("Warning: missed lessons in a row"),
        help_text=_(
            "After this many missed lessons in a row a task 'call the parent' appears. 0 = off."
        ),
        default=2,
        min_value=0,
        max_value=10,
        order=80,
    ),
    SettingDef(
        key="alerts.absence_assignee",
        label=_("Warning about missed lessons goes to"),
        default=1,
        choices=((1, _("Branch administrators")), (2, _("The group's teacher"))),
        order=81,
    ),
    SettingDef(
        key="alerts.debt_days",
        label=_("Warning: debt overdue (days)"),
        help_text=_(
            "A task for the branch administrators when a debt is this many days overdue. 0 = off."
        ),
        default=7,
        min_value=0,
        max_value=180,
        order=82,
    ),
    SettingDef(
        key="alerts.debt_repeat_days",
        label=_("Repeat the debt warning every (days)"),
        help_text=_(
            "A new task if the debt is still unpaid after this many more days. 0 = only once."
        ),
        default=7,
        min_value=0,
        max_value=180,
        order=83,
    ),
    SettingDef(
        key="alerts.lead_hours",
        label=_("Warning: new lead not contacted within (working hours)"),
        help_text=_("Counted only during working hours. 0 = off."),
        default=2,
        min_value=0,
        max_value=72,
        order=84,
    ),
    SettingDef(
        key="alerts.work_start",
        label=_("Working hours start (hour)"),
        default=9,
        min_value=0,
        max_value=23,
        order=85,
    ),
    SettingDef(
        key="alerts.work_end",
        label=_("Working hours end (hour)"),
        default=19,
        min_value=1,
        max_value=24,
        order=86,
    ),
    SettingDef(
        key="alerts.lead_telegram",
        label=_("Also send the lead warning to the manager's Telegram"),
        default=1,
        choices=((1, _("Yes")), (0, _("No"))),
        order=87,
    ),
):
    register_setting(definition)


def _summary(request):
    from . import selectors

    return {"counts": selectors.counts(request.user, request.branch_filter)}


registry.add_widget(
    DashboardWidget("alerts", "alerts/widgets/summary.html", "alerts.view", 1, _summary)
)
