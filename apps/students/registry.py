from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.audit_display import register_labels as register_audit_labels
from apps.core.global_search import SearchHit, SearchProvider, register_search_provider
from apps.core.permissions import register_permission
from apps.core.registry import DashboardWidget, NavItem, registry
from apps.core.roles import Role
from apps.core.system_settings import SettingDef, register_setting

from . import (
    import_kinds,
    sections,  # noqa: F401 - registers Sozlamalar sections
)
from .extensions import register_list_action

D, A, M, T = Role.DIRECTOR, Role.BRANCH_ADMIN, Role.SALES_MANAGER, Role.TEACHER

# Sotuv menejeri creates students only by converting a lead (docs/SPEC.md 6.2).
register_permission("students.create", _("Create students"), {D, A, M})
register_permission("students.view", _("View students"), {D, A, M, T})
register_permission("students.manage", _("Manage students and enrollments"), {D, A})
register_permission("groups.view", _("View groups"), {D, A, M, T})
register_permission("groups.manage", _("Manage groups and lessons"), {D, A})
register_permission("attendance.mark", _("Mark attendance"), {D, A, T})
# The Direktor's; can be given to individual people (Sozlamalar -> Foydalanuvchilar).
register_permission("import.run", _("Import from Excel"), {D}, grantable=True)

register_setting(
    SettingDef(
        key="students.attendance_edit_days",
        label=_("Teachers can edit attendance for (days)"),
        help_text=_("How many days back a teacher may mark or change attendance."),
        default=7,
        min_value=0,
        max_value=60,
        order=50,
    )
)

NAV = [
    NavItem(
        key="students",
        label=_("Students"),
        url_name="students:list",
        icon="users",
        permission="students.view",
        order=20,
        mobile_priority=15,
        active_prefix="/oquvchilar/",
    ),
    NavItem(
        key="groups",
        label=_("Groups"),
        url_name="students:groups",
        icon="book",
        permission="groups.view",
        order=21,
        mobile_priority=25,
        active_prefix="/guruhlar/",
        role_priority={T: 2},
    ),
    NavItem(
        key="attendance",
        label=_("Attendance"),
        url_name="students:attendance",
        icon="calendar",
        permission="attendance.mark",
        order=22,
        mobile_priority=30,
        active_prefix="/davomat/",
        role_priority={T: 1},
    ),
    NavItem(
        key="import",
        label=_("Import"),
        url_name="students:import",
        icon="list",
        permission="import.run",
        order=800,
        mobile_priority=800,
        active_prefix="/import/",
    ),
]
for item in NAV:
    registry.add_nav(item)


def _today_lessons(request):
    """The black "today's schedule" bar: lessons in time order, each marked as done,
    now or later (cancelled ones stay, struck through)."""
    from apps.core import dates

    from . import selectors

    now = dates.now()
    t = now.time().replace(second=0, microsecond=0)
    lessons = list(
        selectors.lessons_on(request.user, now.date(), request.branch_filter).select_related(
            "group", "room"
        )[:40]
    )
    for lesson in lessons:
        if lesson.start_time <= t < lesson.end_time:
            lesson.when = "now"
        elif lesson.end_time <= t:
            lesson.when = "past"
        else:
            lesson.when = "later"
    return {"lessons": lessons, "today": now.date()}


def _awaiting(request):
    from . import selectors

    qs = selectors.awaiting_enrollment(request.user, request.branch_filter)
    return {"count": qs.count(), "students": list(qs.order_by("-created_at")[:5])}


registry.add_widget(
    DashboardWidget(
        "today_lessons",
        "students/widgets/today_lessons.html",
        "attendance.mark",
        -10,
        _today_lessons,
    )
)
registry.add_widget(
    DashboardWidget("awaiting", "students/widgets/awaiting.html", "students.manage", 15, _awaiting)
)

import_kinds.register()


def _call_action(user, students):
    """'Call' button on student cards: the parent's phone, else the student's."""
    from .extensions import ListAction

    return {
        s.pk: [ListAction(f"tel:{s.parent_phone or s.phone}", "phone", _("Call"), 10)]
        for s in students
        if s.parent_phone or s.phone
    }


register_list_action(_call_action)


def _teacher_day_starts(user_ids, start, end):
    """Each teacher's first (not cancelled) lesson per day: when they are expected for
    "Keldim" (core.day_plans)."""
    from django.db.models import Min

    from .models import Lesson

    rows = (
        Lesson.objects.filter(group__teacher_id__in=user_ids, date__gte=start, date__lte=end)
        .exclude(status=Lesson.Status.CANCELLED)
        .values("group__teacher_id", "date")
        .annotate(first=Min("start_time"))
    )
    return {(r["group__teacher_id"], r["date"]): r["first"] for r in rows}


def _register_day_plans():
    from apps.core.day_plans import register_day_start_provider

    register_day_start_provider(_teacher_day_starts)


_register_day_plans()


def _register_reports():
    from apps.core.reports import ReportDef, register_report

    from . import selectors

    register_report(
        ReportDef(
            "ketish-sabablari",
            _("Why students leave"),
            _("Students who left a group, by reason."),
            "reports.view",
            selectors.leave_reasons_report,
            order=55,
            group=_("Students"),
        )
    )


_register_reports()

register_audit_labels(
    {
        "schedule": _("Schedule"),
        "over_capacity": _("Over capacity"),
        "new_group": _("New group"),
        "from_date": _("From"),
        "to_date": _("To"),
        "rows": _("Rows"),
        "groups_created": _("Groups created"),
        "students_created": _("Students created"),
        "students_updated": _("Students updated"),
        "enrollments_created": _("Enrolled into groups"),
        "balances_created": _("Balances created"),
        "discounts_created": _("Discounts created"),
        "related_enrollment": _("Moved from another group"),
        "marked_by": _("Marked by"),
        "marked_at": _("Marked at"),
    }
)


# --- Global search (Ctrl+K) -----------------------------------------------------------


def _search_students(request, query, limit):
    from apps.core.phone import format_phone

    from . import selectors

    qs = selectors.search_students(
        selectors.students_for(request.user, request.branch_filter), query
    ).order_by("last_name", "first_name")
    return [
        SearchHit(
            title=s.full_name,
            url=reverse("students:detail", args=[s.pk]),
            subtitle=" · ".join(
                x for x in (format_phone(s.phone or s.parent_phone), s.branch.name) if x
            ),
        )
        for s in qs[:limit]
    ]


def _search_groups(request, query, limit):
    from apps.core.search import text_search

    from . import selectors

    qs = text_search(
        selectors.groups_for(request.user, request.branch_filter), query, ["name"]
    ).order_by("name")
    return [
        SearchHit(
            title=g.name,
            url=reverse("students:group", args=[g.pk]),
            subtitle=" · ".join(
                x for x in (g.course.name, g.teacher.full_name if g.teacher else "") if x
            ),
        )
        for g in qs[:limit]
    ]


register_search_provider(
    SearchProvider("students", _("Students"), "users", "students.view", _search_students, 10)
)
register_search_provider(
    SearchProvider("groups", _("Groups"), "book", "groups.view", _search_groups, 30)
)
