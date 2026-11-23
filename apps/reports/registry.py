from django.utils.translation import gettext_lazy as _

from apps.core.permissions import register_permission
from apps.core.registry import DashboardWidget, NavItem, registry
from apps.core.roles import Role

from . import definitions  # noqa: F401 - registers the reports

register_permission("reports.view", _("View reports"), {Role.DIRECTOR, Role.BRANCH_ADMIN})

registry.add_nav(
    NavItem(
        key="reports",
        label=_("Reports"),
        url_name="reports:index",
        icon="chart",
        permission="reports.view",
        order=40,
        mobile_priority=45,
        active_prefix="/hisobotlar/",
    )
)


def _overview(request):
    from .dashboard import overview

    return overview(request.user, request.branch_filter)


registry.add_widget(
    DashboardWidget("overview", "reports/widgets/overview.html", "reports.view", 0, _overview)
)
