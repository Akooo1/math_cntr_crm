from django.utils.translation import gettext_lazy as _

from apps.core.audit_display import register_labels as register_audit_labels
from apps.core.permissions import register_permission
from apps.core.registry import DashboardWidget, NavItem, registry
from apps.core.roles import Role

from . import sections  # noqa: F401 - registers Sozlamalar sections

register_audit_labels({"from_stage": _("Stage"), "to_stage": _("Stage"), "done_by": _("Done")})

CRM_ROLES = {Role.DIRECTOR, Role.BRANCH_ADMIN, Role.SALES_MANAGER}

register_permission("crm.leads.view", _("View leads"), CRM_ROLES)
register_permission("crm.leads.edit", _("Work with leads"), CRM_ROLES)
register_permission("crm.leads.convert", _("Convert leads to students"), CRM_ROLES)
register_permission(
    "crm.tasks.view_all", _("See everyone's tasks"), {Role.DIRECTOR, Role.BRANCH_ADMIN}
)

registry.add_nav(
    NavItem(
        key="leads",
        label=_("Leads"),
        url_name="crm:board",
        icon="funnel",
        permission="crm.leads.view",
        order=10,
        mobile_priority=10,
        active_prefix="/lidlar/",
        role_priority={Role.BRANCH_ADMIN: 20, Role.DIRECTOR: 20},
    )
)
registry.add_nav(
    NavItem(
        key="tasks",
        label=_("Tasks"),
        url_name="crm:tasks",
        icon="check",
        permission="crm.leads.view",
        order=11,
        mobile_priority=11,
        active_prefix="/vazifalar/",
        role_priority={Role.BRANCH_ADMIN: 21, Role.DIRECTOR: 21},
    )
)


def _tasks_widget(request):
    from . import selectors

    return {"counts": selectors.task_counts(request.user, request.branch_filter)}


def _pipeline_widget(request):
    from . import selectors

    return {"stages": selectors.stage_counts(request.user, request.branch_filter)}


registry.add_widget(
    DashboardWidget(
        key="crm_tasks",
        template="crm/widgets/tasks.html",
        permission="crm.leads.view",
        order=10,
        context=_tasks_widget,
    )
)
registry.add_widget(
    DashboardWidget(
        key="crm_pipeline",
        template="crm/widgets/pipeline.html",
        permission="crm.leads.view",
        order=20,
        context=_pipeline_widget,
    )
)
