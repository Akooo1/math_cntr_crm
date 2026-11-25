from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.audit_display import register_labels as register_audit_labels
from apps.core.global_search import SearchHit, SearchProvider, register_search_provider
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


# --- Global search (Ctrl+K) -----------------------------------------------------------


def _search_leads(request, query, limit):
    from apps.core.phone import format_phone

    from . import selectors

    qs = selectors.search(selectors.leads_for(request.user, request.branch_filter), query)
    return [
        SearchHit(
            title=lead.full_name,
            url=reverse("crm:lead", args=[lead.pk]),
            subtitle=" · ".join(x for x in (lead.stage.name, format_phone(lead.phone)) if x),
        )
        for lead in qs.order_by("-updated_at")[:limit]
    ]


register_search_provider(
    SearchProvider("leads", _("Leads"), "funnel", "crm.leads.view", _search_leads, 20)
)
