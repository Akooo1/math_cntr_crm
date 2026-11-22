"""Core's own registrations."""

from django.utils.translation import gettext_lazy as _

from .permissions import register_permission
from .registry import NavItem, registry
from .roles import ALL_ROLES, Role
from .system_settings import SettingDef, register_setting

register_permission("dashboard.view", _("View the dashboard"), ALL_ROLES)
register_permission("audit.view", _("View the audit log"), {Role.DIRECTOR})

registry.add_nav(
    NavItem(
        key="home",
        label=_("Home"),
        url_name="core:home",
        icon="home",
        permission="dashboard.view",
        order=0,
        mobile_priority=0,
        active_prefix="/",
    )
)
registry.add_nav(
    NavItem(
        key="audit",
        label=_("Audit log"),
        url_name="core:audit_log",
        icon="journal",
        permission="audit.view",
        order=900,
        mobile_priority=900,
        active_prefix="/jurnal/",
    )
)

register_setting(
    SettingDef(
        key="core.session_timeout_hours",
        label=_("Session length (hours)"),
        help_text=_("How long a user stays logged in without activity."),
        default=12,
        min_value=1,
        max_value=72,
        order=900,
    )
)
