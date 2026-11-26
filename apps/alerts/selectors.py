"""Who sees which warning (docs/SPEC.md §19.3). The same rule guards closing a task."""

from django.db.models import Q

from apps.core.permissions import apply_branch_filter, has_perm, require_perm, scope_by_branch
from apps.core.roles import Role

from .models import Task


def visible_tasks(user, branch_filter=None):
    """Missed lessons: whoever manages students (or the teacher it was given to). Overdue
    debt: only people who may see debts (money never reaches managers or teachers). Leads:
    lead staff; a sales manager sees their own leads' warnings and unassigned ones."""
    if not has_perm(user, "alerts.view"):
        return Task.objects.none()
    kinds = Q(kind=Task.Kind.ABSENCE, assigned_to=user)
    if has_perm(user, "students.manage"):
        kinds |= Q(kind=Task.Kind.ABSENCE)
    if has_perm(user, "billing.debtors.view"):
        kinds |= Q(kind=Task.Kind.DEBT)
    if has_perm(user, "crm.leads.view"):
        if user.role == Role.SALES_MANAGER:
            kinds |= Q(kind=Task.Kind.LEAD) & (Q(assigned_to=user) | Q(assigned_to__isnull=True))
        else:
            kinds |= Q(kind=Task.Kind.LEAD)
    qs = scope_by_branch(Task.objects.filter(kinds), user)
    return apply_branch_filter(qs, branch_filter)


def open_tasks(user, branch_filter=None, kind: str | None = None):
    require_perm(user, "alerts.view")
    qs = visible_tasks(user, branch_filter).filter(closed_at__isnull=True)
    if kind:
        qs = qs.filter(kind=kind)
    return qs.select_related("student", "group", "lead", "assigned_to", "branch").order_by(
        "created_at", "id"
    )


def counts(user, branch_filter=None) -> dict:
    qs = visible_tasks(user, branch_filter).filter(closed_at__isnull=True)
    out = {k: 0 for k in Task.Kind.values}
    for kind in qs.values_list("kind", flat=True):
        out[kind] += 1
    out["total"] = sum(out[k] for k in Task.Kind.values)
    return out


def get_task(user, pk) -> Task:
    from django.http import Http404

    task = visible_tasks(user).filter(pk=pk).first()
    if task is None:
        raise Http404
    return task
