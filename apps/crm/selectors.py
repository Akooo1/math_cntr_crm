"""Reads for CRM. Every selector applies role and branch scope."""

import datetime as dt
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone

from apps.core import dates
from apps.core.permissions import (
    accessible_branch_ids,
    apply_branch_filter,
    has_perm,
    require_perm,
    scope_by_branch,
)
from apps.core.roles import Role
from apps.core.search import text_search
from apps.students import selectors as student_selectors

from .models import FollowUpTask, Lead, LeadStage, TrialLesson

User = get_user_model()


def leads_for(user, branch_filter=None):
    require_perm(user, "crm.leads.view")
    qs = Lead.objects.select_related("stage", "source", "course", "manager", "branch")
    return apply_branch_filter(scope_by_branch(qs, user), branch_filter)


def get_lead(user, pk) -> Lead:
    lead = leads_for(user).filter(pk=pk).first()
    if lead is None:
        raise Http404
    return lead


def search(qs, query: str):
    return text_search(qs, query, ["full_name"], ["phone_normalized", "extra_phone"])


def active_stages():
    return list(LeadStage.objects.filter(is_active=True).order_by("sort_order", "id"))


def stage_of_kind(kind: str) -> LeadStage:
    return LeadStage.objects.get(kind=kind)


def branch_staff(branch_ids):
    """Users a lead can be assigned to: managers and admins of these branches."""
    qs = User.objects.filter(
        is_active=True, role__in=[Role.SALES_MANAGER, Role.BRANCH_ADMIN]
    ).order_by("full_name")
    if branch_ids is not None:
        qs = qs.filter(branch_links__branch_id__in=branch_ids).distinct()
    return qs


# --- Duplicates ----------------------------------------------------------------------


@dataclass
class Duplicates:
    leads: list = field(default_factory=list)  # in the user's scope: shown with links
    students: list = field(default_factory=list)  # in the user's scope
    other_branches: list[str] = field(default_factory=list)  # names only

    def __bool__(self):
        return bool(self.leads or self.students or self.other_branches)


def find_duplicates(user, phones: list[str], *, exclude_lead_id=None) -> Duplicates:
    """Leads and students with any of these phones, in ALL branches (docs/SPEC.md 6.2).

    Records outside the user's branches are reported by branch name only.
    """
    phones = sorted({p for p in phones if p})
    result = Duplicates()
    if not phones:
        return result
    allowed = accessible_branch_ids(user)
    in_scope = lambda branch_id: allowed is None or branch_id in allowed  # noqa: E731
    leads = Lead.objects.filter(Q(phone__in=phones) | Q(extra_phone__in=phones)).select_related(
        "branch", "stage"
    )
    if exclude_lead_id:
        leads = leads.exclude(pk=exclude_lead_id)
    other = set()
    for lead in leads:
        if in_scope(lead.branch_id):
            result.leads.append(lead)
        else:
            other.add(lead.branch.name)
    for student in student_selectors.find_by_phones(phones):
        if in_scope(student.branch_id):
            result.students.append(student)
        else:
            other.add(student.branch.name)
    result.other_branches = sorted(other)
    return result


# --- Board ---------------------------------------------------------------------------

BOARD_LIMIT = 50
CLOSED_LIMIT = 30  # won / lost columns show only the latest leads


def board(user, branch_filter, *, query="", source=None, manager=None, course=None):
    qs = leads_for(user, branch_filter)
    qs = search(qs, query)
    if source:
        qs = qs.filter(source_id=source)
    if manager:
        qs = qs.filter(manager_id=manager)
    if course:
        qs = qs.filter(course_id=course)
    counts = dict(qs.values_list("stage_id").annotate(n=Count("id")).values_list("stage_id", "n"))
    columns = []
    for stage in active_stages():
        limit = CLOSED_LIMIT if stage.kind in ("won", "lost") else BOARD_LIMIT
        leads = list(qs.filter(stage=stage).order_by("-updated_at")[:limit])
        columns.append({"stage": stage, "leads": leads, "count": counts.get(stage.id, 0)})
    return columns


def stage_counts(user, branch_filter) -> list[dict]:
    qs = leads_for(user, branch_filter)
    counts = dict(qs.values_list("stage_id").annotate(n=Count("id")).values_list("stage_id", "n"))
    return [{"stage": s, "count": counts.get(s.id, 0)} for s in active_stages()]


# --- Tasks ---------------------------------------------------------------------------


def tasks_for(user, branch_filter=None, *, everyone=False):
    """Open tasks: the user's own, or (admin/director) everyone's in their branches."""
    require_perm(user, "crm.leads.view")
    qs = FollowUpTask.objects.filter(done_at__isnull=True).select_related(
        "lead", "lead__stage", "assigned_to"
    )
    qs = apply_branch_filter(
        scope_by_branch(qs, user, field="lead__branch"), branch_filter, "lead__branch"
    )
    if not (everyone and has_perm(user, "crm.tasks.view_all")):
        qs = qs.filter(assigned_to=user)
    return qs.order_by("due_at", "id")


def group_tasks(tasks) -> dict:
    now = dates.now()
    today = now.date()
    groups = {"overdue": [], "today": [], "upcoming": []}
    for task in tasks:
        if task.due_at < now:
            groups["overdue"].append(task)
        elif timezone.localtime(task.due_at).date() == today:
            groups["today"].append(task)
        else:
            groups["upcoming"].append(task)
    return groups


def task_counts(user, branch_filter=None) -> dict:
    groups = group_tasks(tasks_for(user, branch_filter))
    return {k: len(v) for k, v in groups.items()}


def get_task(user, pk) -> FollowUpTask:
    require_perm(user, "crm.leads.view")
    qs = scope_by_branch(FollowUpTask.objects.select_related("lead"), user, field="lead__branch")
    task = qs.filter(pk=pk).first()
    if task is None:
        raise Http404
    return task


# --- Trial lessons -------------------------------------------------------------------


def trials_for(user, branch_filter=None, *, from_date: dt.date | None = None):
    require_perm(user, "crm.leads.view")
    qs = TrialLesson.objects.select_related(
        "lead", "lead__stage", "lead__course", "group", "lesson"
    )
    qs = apply_branch_filter(
        scope_by_branch(qs, user, field="lead__branch"), branch_filter, "lead__branch"
    )
    if from_date:
        qs = qs.filter(scheduled_date__gte=from_date)
    return qs.order_by("scheduled_date", "id")


def get_trial(user, pk) -> TrialLesson:
    trial = trials_for(user).filter(pk=pk).first()
    if trial is None:
        raise Http404
    return trial
