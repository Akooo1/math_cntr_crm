"""Early warnings: the checking job and closing tasks (docs/SPEC.md §19).

`run_checks()` runs every 15 minutes (deploy/crontab). It is idempotent: each cause has a
unique key, so a task is made once; tasks whose cause went away are closed as "resolved".
"""

import datetime as dt
from collections import defaultdict

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing import selectors as billing_selectors
from apps.core import dates
from apps.core.events import publish
from apps.core.permissions import has_perm
from apps.core.system_settings import get_setting
from apps.crm.models import Lead, LeadActivity, LeadStage
from apps.students.models import Attendance, Enrollment, Lesson

from . import domain
from .events import AlertCreated
from .models import Task

ASSIGN_ADMINS, ASSIGN_TEACHER = 1, 2
# A first run on old data must not flood the list: only recent causes count.
ABSENCE_LOOKBACK_DAYS = 14
LEAD_LOOKBACK_DAYS = 3
CONTACT_KINDS = [
    LeadActivity.Kind.CALL,
    LeadActivity.Kind.NOTE,
    LeadActivity.Kind.STAGE_CHANGE,
    LeadActivity.Kind.TRIAL,
    LeadActivity.Kind.CONVERTED,
]


def _create(**fields) -> Task | None:
    try:
        with transaction.atomic():
            task = Task.objects.create(**fields)
    except IntegrityError:  # already made for this cause
        return None
    publish(AlertCreated(task_id=task.pk, kind=task.kind, assigned_to_id=task.assigned_to_id))
    return task


def _resolve(tasks) -> int:
    return tasks.update(closed_at=timezone.now(), closed_how=Task.Closed.RESOLVED)


# --- absences -------------------------------------------------------------------------------


def check_absences(today: dt.date) -> int:
    need = get_setting("alerts.absence_streak")
    open_tasks = Task.objects.filter(kind=Task.Kind.ABSENCE, closed_at__isnull=True)
    if need <= 0:
        return 0
    marks = defaultdict(list)
    for enrollment_id, lesson_id, status in (
        Attendance.objects.filter(
            enrollment__status__in=Enrollment.OPEN,
            lesson__date__gte=today - dt.timedelta(days=90),
            lesson__date__lte=today,
        )
        .order_by("enrollment_id", "-lesson__date", "-lesson__start_time")
        .values_list("enrollment_id", "lesson_id", "status")
    ):
        marks[enrollment_id].append((lesson_id, status))
    streaks = {}
    for enrollment_id, rows in marks.items():
        count, first = domain.absence_streak(rows)
        if count >= need:
            streaks[enrollment_id] = (count, first, rows[0][0])
    # Close tasks whose student came again or left the group.
    _resolve(open_tasks.exclude(details__enrollment__in=list(streaks)))
    if not streaks:
        return 0
    enrollments = Enrollment.objects.select_related("group").in_bulk(list(streaks))
    last_dates = dict(
        Lesson.objects.filter(pk__in=[s[2] for s in streaks.values()]).values_list("pk", "date")
    )
    assign_teacher = get_setting("alerts.absence_assignee") == ASSIGN_TEACHER
    made = 0
    for enrollment_id, (count, first, last) in streaks.items():
        e = enrollments[enrollment_id]
        if last_dates.get(last) and last_dates[last] < today - dt.timedelta(
            days=ABSENCE_LOOKBACK_DAYS
        ):
            continue
        key = f"absence:{enrollment_id}:{first}"
        existing = Task.objects.filter(key=key, closed_at__isnull=True).first()
        if existing:
            if existing.details.get("missed") != count:
                existing.details = {**existing.details, "missed": count}
                existing.save(update_fields=["details"])
            continue
        made += bool(
            _create(
                kind=Task.Kind.ABSENCE,
                key=key,
                branch_id=e.group.branch_id,
                student_id=e.student_id,
                group_id=e.group_id,
                assigned_to_id=e.group.teacher_id if assign_teacher else None,
                details={"enrollment": enrollment_id, "missed": count},
            )
        )
    return made


# --- debts ----------------------------------------------------------------------------------


def check_debts(today: dt.date) -> int:
    first_after = get_setting("alerts.debt_days")
    repeat = get_setting("alerts.debt_repeat_days")
    open_tasks = Task.objects.filter(kind=Task.Kind.DEBT, closed_at__isnull=True)
    summary = billing_selectors.overdue_summary() if first_after > 0 else {}
    due = {}
    for sid, d in summary.items():
        days = (today - d["oldest"]).days
        round_no = domain.debt_round(days, first_after, repeat)
        if round_no is not None and d["branch_id"]:
            due[sid] = (round_no, days, d)
    _resolve(open_tasks.exclude(student_id__in=list(due)))
    made = 0
    still_open = set(open_tasks.values_list("student_id", flat=True))
    for sid, (round_no, days, d) in due.items():
        if sid in still_open:  # one open debt task per student; refresh its numbers
            open_tasks.filter(student_id=sid).update(
                details={"overdue": d["overdue"], "days": days, "oldest": d["oldest"].isoformat()}
            )
            continue
        made += bool(
            _create(
                kind=Task.Kind.DEBT,
                key=f"debt:{sid}:{d['oldest']:%Y%m%d}:{round_no}",
                branch_id=d["branch_id"],
                student_id=sid,
                details={"overdue": d["overdue"], "days": days, "oldest": d["oldest"].isoformat()},
            )
        )
    return made


# --- leads ----------------------------------------------------------------------------------


def check_leads(now: dt.datetime) -> int:
    hours = get_setting("alerts.lead_hours")
    start, end = get_setting("alerts.work_start"), get_setting("alerts.work_end")
    open_tasks = Task.objects.filter(kind=Task.Kind.LEAD, closed_at__isnull=True)
    contacted = LeadActivity.objects.filter(kind__in=CONTACT_KINDS).values("lead_id")
    _resolve(
        open_tasks.filter(lead_id__in=contacted)
        | open_tasks.exclude(lead__stage__kind=LeadStage.Kind.NEW)
    )
    if hours <= 0 or start >= end:
        return 0
    leads = (
        Lead.objects.filter(
            stage__kind=LeadStage.Kind.NEW,
            created_at__gte=now - dt.timedelta(days=LEAD_LOOKBACK_DAYS),
        )
        .exclude(pk__in=contacted)
        .exclude(pk__in=Task.objects.filter(kind=Task.Kind.LEAD).values("lead_id"))
    )
    made = 0
    for lead in leads:
        local = timezone.localtime(lead.created_at).replace(tzinfo=None)
        deadline = domain.response_deadline(local, hours, start, end)
        deadline = timezone.make_aware(deadline, timezone.get_current_timezone())
        if now < deadline:
            continue
        made += bool(
            _create(
                kind=Task.Kind.LEAD,
                key=f"lead:{lead.pk}",
                branch_id=lead.branch_id,
                lead=lead,
                assigned_to_id=lead.manager_id,
                due_at=deadline,
                details={"hours": hours},
            )
        )
    return made


def run_checks() -> dict:
    now = dates.now()
    return {
        "absence": check_absences(now.date()),
        "debt": check_debts(now.date()),
        "lead": check_leads(now),
    }


# --- people closing tasks -------------------------------------------------------------------


def can_handle(user, task: Task) -> bool:
    """Who may see and close a task. Server-side; the list uses the same rule."""
    from .selectors import visible_tasks

    return visible_tasks(user).filter(pk=task.pk).exists()


def close(*, actor, task: Task) -> Task:
    if not has_perm(actor, "alerts.view") or not can_handle(actor, task):
        raise PermissionDenied
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task.pk)
        if task.closed_at is None:
            task.closed_at = timezone.now()
            task.closed_by = actor
            task.closed_how = Task.Closed.DONE
            task.save(update_fields=["closed_at", "closed_by", "closed_how"])
    return task


def reopen(*, actor, task: Task) -> Task:
    """Undo "done" (the toast's undo button). A task resolved by itself stays closed."""
    if not has_perm(actor, "alerts.view") or not can_handle(actor, task):
        raise PermissionDenied
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task.pk)
        if task.closed_how == Task.Closed.DONE:
            task.closed_at = None
            task.closed_by = None
            task.closed_how = ""
            task.save(update_fields=["closed_at", "closed_by", "closed_how"])
    return task
