"""Reads for the students module. Every selector applies role and branch scope.

O'qituvchi sees only groups they teach and the students currently in those groups.
"""

import datetime as dt
from dataclasses import dataclass, field

from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.http import Http404

from apps.core import dates
from apps.core.permissions import (
    accessible_branch_ids,
    apply_branch_filter,
    require_perm,
    scope_by_branch,
)
from apps.core.roles import Role
from apps.core.search import text_search

from .domain.schedule import Slot, is_active_on, is_frozen_on, lesson_plan
from .models import Enrollment, Group, Lesson, Student

OPEN = Enrollment.OPEN


def _is_teacher(user) -> bool:
    return user.role == Role.TEACHER


# --- Students -----------------------------------------------------------------------


def students_for(user, branch_filter=None):
    require_perm(user, "students.view")
    qs = Student.objects.select_related("branch")
    qs = apply_branch_filter(scope_by_branch(qs, user), branch_filter)
    if _is_teacher(user):
        mine = Enrollment.objects.filter(
            student=OuterRef("pk"), group__teacher=user, status__in=OPEN
        )
        qs = qs.filter(Exists(mine))
    return qs


def get_student(user, pk) -> Student:
    student = students_for(user).filter(pk=pk).first()
    if student is None:
        raise Http404
    return student


def search_students(qs, query: str):
    return text_search(
        qs,
        query,
        ["last_name", "first_name", "parent_name"],
        ["phone", "parent_phone", "extra_phone"],
    )


def with_open_groups(qs):
    return qs.prefetch_related(
        Prefetch(
            "enrollments",
            queryset=Enrollment.objects.filter(status__in=OPEN).select_related(
                "group", "group__course"
            ),
            to_attr="open_enrollments",
        )
    )


def awaiting_enrollment(user, branch_filter=None):
    """Students who have never been enrolled into a group (e.g. just converted leads)."""
    return students_for(user, branch_filter).filter(enrollments__isnull=True)


def find_by_phones(phones: list[str]):
    """Students in any branch with one of these phones (for duplicate warnings).

    Deliberately not branch-scoped: callers decide what to reveal about other branches.
    """
    phones = [p for p in phones if p]
    if not phones:
        return Student.objects.none()
    return Student.objects.filter(
        Q(phone__in=phones) | Q(parent_phone__in=phones) | Q(extra_phone__in=phones)
    ).select_related("branch")


def student_status(student: Student) -> str:
    """'active' | 'frozen' | 'left' | 'new' — derived from enrollments, never stored."""
    statuses = set(student.enrollments.values_list("status", flat=True))
    if Enrollment.Status.ACTIVE in statuses:
        return "active"
    if Enrollment.Status.FROZEN in statuses:
        return "frozen"
    if statuses:
        return "left"
    return "new"


# --- Groups ---------------------------------------------------------------------------


def groups_for(user, branch_filter=None):
    require_perm(user, "groups.view")
    qs = Group.objects.select_related("course", "teacher", "room", "branch")
    qs = apply_branch_filter(scope_by_branch(qs, user), branch_filter)
    if _is_teacher(user):
        qs = qs.filter(teacher=user)
    return qs.annotate(
        open_count=Count("enrollments", filter=Q(enrollments__status__in=OPEN), distinct=True)
    )


def get_group(user, pk) -> Group:
    group = groups_for(user).filter(pk=pk).first()
    if group is None:
        raise Http404
    return group


def enrollable_groups(user, student: Student):
    return groups_for(user).filter(branch=student.branch).exclude(status=Group.Status.FINISHED)


# --- Lessons and attendance -----------------------------------------------------------


def lessons_for(user, branch_filter=None):
    groups = groups_for(user, branch_filter)
    return Lesson.objects.filter(group__in=groups.values("pk")).select_related(
        "group", "group__course", "room"
    )


def get_lesson(user, pk) -> Lesson:
    lesson = lessons_for(user).filter(pk=pk).first()
    if lesson is None:
        raise Http404
    return lesson


def lessons_on(user, day: dt.date, branch_filter=None):
    return lessons_for(user, branch_filter).filter(date=day).order_by("start_time", "group__name")


def roster(lesson: Lesson) -> list[Enrollment]:
    """Enrollments that attend this lesson: open on the date and not frozen that day."""
    candidates = (
        Enrollment.objects.filter(group_id=lesson.group_id, start_date__lte=lesson.date)
        .filter(Q(end_date__isnull=True) | Q(end_date__gt=lesson.date))
        .select_related("student")
        .prefetch_related("freezes")
        .order_by("student__last_name", "student__first_name")
    )
    return [
        e
        for e in candidates
        if is_active_on(e.start_date, e.end_date, lesson.date)
        and not is_frozen_on([(f.from_date, f.to_date) for f in e.freezes.all()], lesson.date)
    ]


def upcoming_lessons(group: Group, limit=10):
    return group.lessons.filter(date__gte=dates.today()).order_by("date", "start_time")[:limit]


def recent_lessons(group: Group, limit=10):
    return (
        group.lessons.filter(date__lt=dates.today())
        .annotate(
            present=Count("attendance", filter=Q(attendance__status="present")),
            marked=Count("attendance"),
        )
        .order_by("-date", "-start_time")[:limit]
    )


def planned_lesson_dates(group: Group, first: dt.date, last: dt.date) -> list[dt.date]:
    """Lesson dates the weekly schedule gives between `first` and `last` (inclusive), minus
    lessons cancelled by hand. Billing prorates by these (SPEC 6.4.2)."""
    slots = [Slot(s.weekday, s.start_time, s.end_time) for s in group.slots.all()]
    cancelled = set(
        Lesson.objects.filter(
            group=group, date__gte=first, date__lte=last, status=Lesson.Status.CANCELLED
        ).values_list("date", "start_time")
    )
    return [
        p.date for p in lesson_plan(slots, first, last) if (p.date, p.start_time) not in cancelled
    ]


def leave_reasons_report(user, p):
    """Report "Why students leave": students who left a group in the period, by reason."""
    from django.utils.translation import gettext as _

    from apps.core.reports import Col, Result

    from .models import EnrollmentEvent

    require_perm(user, "students.view")
    events = EnrollmentEvent.objects.filter(
        kind=EnrollmentEvent.Kind.LEFT,
        effective_date__gte=p.date_from,
        effective_date__lte=p.date_to,
    )
    events = scope_by_branch(events, user, field="enrollment__group__branch")
    if p.branch_id:
        events = events.filter(enrollment__group__branch_id=p.branch_id)
    counts = list(events.values("leave_reason__name").annotate(n=Count("id")).order_by("-n"))
    total = sum(r["n"] for r in counts)
    rows = [
        [r["leave_reason__name"] or _("Not given"), r["n"], (r["n"] / total) if total else 0]
        for r in counts
    ]
    return Result(
        columns=[Col(_("Reason")), Col(_("Students"), "int"), Col(_("Share"), "percent")],
        rows=rows,
        totals=[_("Total"), total, 1 if total else 0],
        note=_(
            "Students who left a group in the period (a student who left two groups counts twice)."
        ),
    )


# --- Already registered? (docs/SPEC.md §24) -------------------------------------------------


@dataclass
class Match:
    reason: str  # "phone" (the same student phone: refused), "parent_phone", "name"
    student: Student | None  # None when the student is in a branch the user can't see
    branch_name: str


@dataclass
class Matches:
    blocking: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def __bool__(self):
        return bool(self.blocking or self.warnings)


def own_phone_owner(phone: str, exclude_id=None) -> Student | None:
    """The student whose own phone this already is (a phone belongs to one student)."""
    if not phone:
        return None
    qs = Student.objects.filter(phone=phone).select_related("branch")
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.first()


def matches(user, data: dict, exclude_id=None) -> Matches:
    """Students already registered who look like `data`, in ALL branches. The same own
    phone is refused; the same parent's phone (often a brother or sister) or the same name
    and date of birth only warn. Outside the user's branches only the branch is shown."""
    from apps.core.text import search_key

    allowed = accessible_branch_ids(user)
    out, seen = Matches(), set()

    def add(kind, s, bucket):
        if s.pk in seen or s.pk == exclude_id:
            return
        seen.add(s.pk)
        visible = allowed is None or s.branch_id in allowed
        bucket.append(Match(kind, s if visible else None, s.branch.name))

    phone, parent = data.get("phone") or "", data.get("parent_phone") or ""
    owner = own_phone_owner(phone, exclude_id)
    if owner:
        add("phone", owner, out.blocking)
    phones = [p for p in (phone, parent, data.get("extra_phone") or "") if p]
    if phones:
        for s in find_by_phones(phones).exclude(pk=exclude_id or 0):
            add("parent_phone", s, out.warnings)
    last, first, birth = data.get("last_name"), data.get("first_name"), data.get("birth_date")
    if last and first and birth:
        key = (search_key(last), search_key(first))
        for s in Student.objects.filter(birth_date=birth).select_related("branch"):
            if (search_key(s.last_name), search_key(s.first_name)) == key:
                add("name", s, out.warnings)
    return out
