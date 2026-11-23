"""Staff attendance reads (docs/SPEC.md §14)."""

import datetime as dt

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils.translation import gettext_lazy as _

from apps.core import dates
from apps.core.permissions import accessible_branch_ids, require_perm
from apps.core.reports import Col, Result
from apps.core.roles import Role
from apps.settings.models import Branch

from .domain import rules
from .models import BranchLocation, CheckIn, Schedule

STATUS_ORDER = ["not_yet", "late", "on_time", "no_schedule", "day_off"]


def staff(user=None, branch_id: int | None = None):
    """Employees who mark arrival: everyone active except the Direktor."""
    qs = get_user_model().objects.filter(is_active=True).exclude(role=Role.DIRECTOR)
    ids = accessible_branch_ids(user) if user is not None else None
    if ids is not None:
        qs = qs.filter(branch_links__branch_id__in=ids)
    if branch_id:
        qs = qs.filter(branch_links__branch_id=branch_id)
    return qs.distinct().order_by("full_name")


def board(user, day: dt.date, branch_id: int | None = None) -> dict:
    require_perm(user, "staff.attendance.view")
    people = list(staff(user, branch_id))
    schedules = {s.user_id: s for s in Schedule.objects.filter(user__in=people)}
    checkins = {
        c.user_id: c
        for c in CheckIn.objects.filter(date=day, user__in=people).select_related("branch")
    }
    rows = []
    for person in people:
        schedule, checkin = schedules.get(person.pk), checkins.get(person.pk)
        works = schedule is not None and rules.works_on(schedule.workdays, day)
        st = rules.status(
            scheduled=schedule is not None,
            works_today=works,
            checked_in=checkin is not None,
            late=checkin.late_minutes if checkin else 0,
        )
        if st == "not_yet" and day < dates.today():
            st = "absent"
        rows.append({"user": person, "schedule": schedule, "checkin": checkin, "status": st})
    order = {s: i for i, s in enumerate(["absent", *STATUS_ORDER])}
    rows.sort(key=lambda r: (order[r["status"]], r["user"].full_name))
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in order}
    return {"day": day, "rows": rows, "counts": counts}


def my_today(user) -> dict:
    today = dates.today()
    schedule = Schedule.objects.filter(user=user).first()
    return {
        "checkin": CheckIn.objects.filter(user=user, date=today).select_related("branch").first(),
        "schedule": schedule,
        "works_today": schedule is not None and rules.works_on(schedule.workdays, today),
        "has_location": BranchLocation.objects.filter(branch_id__in=user.branch_ids).exists(),
    }


def locations() -> list[dict]:
    locs = {loc.branch_id: loc for loc in BranchLocation.objects.all()}
    rows = []
    for b in Branch.objects.filter(is_active=True).order_by("name"):
        loc = locs.get(b.pk)
        coords = f"{loc.latitude:.6f}, {loc.longitude:.6f}" if loc else ""
        rows.append({"branch": b, "location": loc, "coords": coords})
    return rows


def schedules() -> list[dict]:
    people = list(staff())
    by_user = {s.user_id: s for s in Schedule.objects.filter(user__in=people)}
    return [{"user": p, "schedule": by_user.get(p.pk)} for p in people]


def workdays_between(workdays: list[int], start: dt.date, end: dt.date) -> int:
    n, d = 0, start
    while d <= end:
        if d.isoweekday() in workdays:
            n += 1
        d += dt.timedelta(days=1)
    return n


def monthly_report(user, p) -> Result:
    """Per employee for the period: workdays (by the current schedule), arrivals, late
    arrivals and minutes, missed workdays (up to yesterday)."""
    require_perm(user, "staff.attendance.view")
    people = list(staff(user, p.branch_id))
    schedules_by_user = {s.user_id: s for s in Schedule.objects.filter(user__in=people)}
    stats = {
        r["user_id"]: r
        for r in CheckIn.objects.filter(user__in=people, date__gte=p.date_from, date__lte=p.date_to)
        .values("user_id")
        .annotate(
            came=Count("id"),
            late=Count("id", filter=Q(late_minutes__gt=0)),
            minutes=Sum("late_minutes"),
        )
    }
    yesterday = dates.today() - dt.timedelta(days=1)
    rows = []
    for person in people:
        s = schedules_by_user.get(person.pk)
        st = stats.get(person.pk, {})
        end = min(p.date_to, yesterday)
        workdays = workdays_between(s.workdays, p.date_from, end) if s else 0
        came_on_workdays = (
            CheckIn.objects.filter(user=person, date__gte=p.date_from, date__lte=end)
            .filter(date__week_day__in=[(d % 7) + 1 for d in s.workdays])
            .count()
            if s
            else 0
        )
        rows.append(
            [
                person.full_name,
                person.get_role_display(),
                workdays,
                st.get("came", 0),
                st.get("late", 0),
                st.get("minutes") or 0,
                max(workdays - came_on_workdays, 0),
            ]
        )
    columns = [
        Col(_("Employee")),
        Col(_("Role")),
        Col(_("Workdays"), "int"),
        Col(_("Arrived"), "int"),
        Col(_("Late"), "int"),
        Col(_("Minutes late"), "int"),
        Col(_("Missed"), "int"),
    ]
    totals = [_("Total"), "", *[sum(r[i] for r in rows) for i in range(2, 7)]]
    return Result(
        columns=columns,
        rows=rows,
        totals=totals,
        note=_(
            "Workdays follow each employee's current schedule. Missed days are counted up "
            "to yesterday."
        ),
    )
