from django.utils.translation import gettext_lazy as _

from apps.core.permissions import register_permission
from apps.core.registry import NavItem, registry
from apps.core.roles import Role

from . import sections  # noqa: F401 - registers the Sozlamalar sections
from .selectors import branches_for_switcher, center_name

register_permission("settings.manage", _("Manage settings"), {Role.DIRECTOR})
register_permission(
    "accounts.users.manage",
    _("Manage users, roles and rights"),
    {Role.DIRECTOR},
    owner_only=True,
)

registry.add_nav(
    NavItem(
        key="settings",
        label=_("Settings"),
        url_name="settings:index",
        icon="cog",
        permission="settings.manage",
        order=950,
        mobile_priority=50,
        active_prefix="/sozlamalar/",
    )
)
registry.center_name_provider = center_name
registry.branch_options_provider = branches_for_switcher
