from django.utils.translation import gettext_lazy as _

from apps.core.audit_display import register_labels as register_audit_labels
from apps.core.permissions import register_permission
from apps.core.registry import DashboardWidget, NavItem, registry
from apps.core.reports import ReportDef, register_report
from apps.core.roles import Role
from apps.core.settings_panel import register_section
from apps.core.system_settings import SettingDef, register_setting

register_permission(
    "staff.checkin",
    _("Mark own arrival"),
    {Role.BRANCH_ADMIN, Role.SALES_MANAGER, Role.TEACHER},
)
register_permission("staff.attendance.view", _("See staff attendance"), {Role.DIRECTOR})

registry.add_nav(
    NavItem(
        key="staff_attendance",
        label=_("Staff attendance"),
        url_name="staff:board",
        icon="clock",
        permission="staff.attendance.view",
        order=47,
        mobile_priority=55,
        active_prefix="/xodimlar-davomati/",
    )
)

register_setting(
    SettingDef(
        key="staff.grace_minutes",
        label=_("Late after (minutes)"),
        help_text=_("Arriving this many minutes after the start time still counts as on time."),
        default=10,
        min_value=0,
        max_value=60,
        order=70,
    )
)

register_audit_labels(
    {
        "latitude": _("Latitude"),
        "longitude": _("Longitude"),
        "radius_m": _("Radius (m)"),
        "start_time": _("Start time"),
        "workdays": _("Workdays"),
        "checked_in_at": _("Arrived at"),
        "accuracy_m": _("GPS accuracy (m)"),
        "distance_m": _("Distance (m)"),
        "expected_start": _("Start time"),
        "late_minutes": _("Minutes late"),
        "source": _("Source"),
        "ip": _("IP address"),
        "user_agent": _("Browser"),
        "updated_by": _("Updated by"),
    }
)


def _register():
    from . import selectors
    from .sections import LocationSection, ScheduleSection

    register_section(LocationSection())
    register_section(ScheduleSection())
    register_report(
        ReportDef(
            "xodimlar-davomati",
            _("Staff attendance"),
            _("Arrivals, late arrivals and missed workdays per employee."),
            "staff.attendance.view",
            selectors.monthly_report,
            order=80,
            group=_("Staff"),
        )
    )


_register()


def _my_day(request):
    from . import selectors

    return selectors.my_today(request.user)


def _board_summary(request):
    from apps.core import dates

    from . import selectors

    return selectors.board(request.user, dates.today(), request.branch_filter)


registry.add_widget(
    DashboardWidget("checkin", "staff/widgets/checkin.html", "staff.checkin", -1, _my_day)
)
registry.add_widget(
    DashboardWidget(
        "staff_today", "staff/widgets/today.html", "staff.attendance.view", 3, _board_summary
    )
)
