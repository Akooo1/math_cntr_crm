from django.utils.dates import MONTHS
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _

from apps.core.audit_display import register_labels as register_audit_labels
from apps.core.permissions import register_permission
from apps.core.registry import DashboardWidget, NavItem, registry
from apps.core.roles import Role
from apps.core.settings_panel import register_section
from apps.core.system_settings import SettingDef, register_setting

register_permission("salaries.manage", _("Manage teacher salaries"), {Role.DIRECTOR})
register_permission("salaries.view_own", _("See own salary"), {Role.TEACHER})

registry.add_nav(
    NavItem(
        key="salaries",
        label=_("Salaries"),
        url_name="salaries:index",
        icon="wallet",
        permission="salaries.manage",
        order=45,
        mobile_priority=50,
        active_prefix="/maosh/",
    )
)
registry.add_nav(
    NavItem(
        key="my_salary",
        label=_("My salary"),
        url_name="salaries:mine",
        icon="wallet",
        permission="salaries.view_own",
        order=46,
        mobile_priority=50,
        active_prefix="/maoshim/",
    )
)

register_setting(
    SettingDef(
        key="salaries.default_rate_bp",
        label=_("Default teacher share"),
        help_text=_("Share of the money students paid. A teacher's own rate overrides it."),
        default=5000,
        choices=tuple((bp, f"{bp // 100}%") for bp in range(2000, 8500, 500)),
        order=60,
    )
)
register_setting(
    SettingDef(
        key="salaries.start_month",
        label=_("Salaries are calculated from"),
        help_text=_("Payments made before this month don't count toward salaries."),
        default=202612,
        choices=tuple(
            (y * 100 + m, format_lazy("{} {}", MONTHS[m], y))
            for y in range(2025, 2029)
            for m in range(1, 13)
        ),
        order=61,
    )
)

register_audit_labels(
    {
        "rate_bp": _("Rate"),
        "effective_from": _("Effective from"),
        "payment_month": _("Payment month"),
        "base": _("Money paid"),
        "paid_on": _("Date"),
        "cancels": _("Cancels"),
        "teachers": _("Teachers"),
        "line_count": _("Lines"),
        "total": _("Total"),
    }
)


def _register():
    from .sections import RateSection

    register_section(RateSection())


_register()


def _my_salary(request):
    from . import selectors

    return selectors.own_summary(request.user)


registry.add_widget(
    DashboardWidget(
        "my_salary", "salaries/widgets/my_salary.html", "salaries.view_own", 5, _my_salary
    )
)
