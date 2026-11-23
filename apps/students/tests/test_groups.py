import datetime as dt

import pytest
import time_machine
from django.core.exceptions import ValidationError

from apps.core.models import AuditLog
from apps.core.roles import Role
from apps.students import services
from apps.students.models import Attendance, Lesson
from tests.factories import UserFactory, make_group, make_student

pytestmark = pytest.mark.django_db
D = dt.date


@pytest.fixture(autouse=True)
def frozen_clock():
    with time_machine.travel(dt.datetime(2026, 10, 15, 9, 0, tzinfo=dt.UTC), tick=False):
        yield


def test_group_creates_lessons_for_fixed_period(admin_a, branch_a):
    group = make_group(admin_a, branch_a, start=D(2026, 9, 1), end=D(2026, 9, 30), days=(2, 4))
    dates = list(group.lessons.values_list("date", flat=True))
    assert len(dates) == 9  # Tue/Thu in September 2026
    assert all(d.isoweekday() in (2, 4) for d in dates)
    assert AuditLog.objects.filter(action="students.group.create").exists()


def test_open_ended_group_gets_rolling_horizon(admin_a, branch_a):
    group = make_group(admin_a, branch_a, start=D(2026, 9, 1), days=(1,))
    last = group.lessons.order_by("-date").first().date
    assert last >= D(2026, 10, 15) + dt.timedelta(days=80)


def test_schedule_change_keeps_past_and_marked_lessons(admin_a, branch_a):
    group = make_group(admin_a, branch_a, start=D(2026, 9, 1), end=D(2026, 12, 31), days=(1, 3))
    past = group.lessons.filter(date__lt=D(2026, 10, 15)).count()
    services.save_group(
        actor=admin_a,
        group=group,
        slots=[{"weekday": 5, "start_time": dt.time(10), "end_time": dt.time(11), "room": None}],
    )
    assert group.lessons.filter(date__lt=D(2026, 10, 15)).count() == past  # history untouched
    future = group.lessons.filter(date__gte=D(2026, 10, 15))
    assert {lesson.date.isoweekday() for lesson in future} == {5}


def test_generate_lessons_is_idempotent(admin_a, branch_a):
    group = make_group(admin_a, branch_a, start=D(2026, 9, 1), end=D(2026, 10, 31))
    before = group.lessons.count()
    assert services.generate_lessons(group) == 0
    assert group.lessons.count() == before


def test_teacher_must_work_in_branch(admin_a, branch_a, branch_b):
    outsider = UserFactory(role=Role.TEACHER, branches=[branch_b])
    with pytest.raises(ValidationError):
        make_group(admin_a, branch_a, teacher=outsider)
    with pytest.raises(ValidationError):
        make_group(admin_a, branch_a, teacher=admin_a)  # not a teacher


def test_cancel_and_restore_lesson(admin_a, branch_a):
    group = make_group(admin_a, branch_a, start=D(2026, 10, 1), end=D(2026, 10, 31))
    lesson = group.lessons.filter(date__gt=D(2026, 10, 15)).first()
    with pytest.raises(ValidationError):
        services.cancel_lesson(actor=admin_a, lesson=lesson, reason=" ")
    services.cancel_lesson(actor=admin_a, lesson=lesson, reason="Bayram")
    lesson.refresh_from_db()
    assert lesson.status == Lesson.Status.CANCELLED
    services.generate_lessons(group)
    lesson.refresh_from_db()
    assert lesson.status == Lesson.Status.CANCELLED  # regeneration doesn't undo it
    services.restore_lesson(actor=admin_a, lesson=lesson)
    lesson.refresh_from_db()
    assert lesson.status == Lesson.Status.SCHEDULED
    assert AuditLog.objects.filter(action="students.lesson.cancel", reason="Bayram").exists()


def test_cannot_cancel_lesson_with_attendance(admin_a, branch_a):
    group = make_group(admin_a, branch_a, start=D(2026, 10, 1), end=D(2026, 10, 31))
    student = make_student(admin_a, branch_a)
    services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 10, 1))
    lesson = group.lessons.filter(date__lt=D(2026, 10, 15)).first()
    services.mark_attendance(actor=admin_a, lesson=lesson, student_id=student.pk, status="present")
    with pytest.raises(ValidationError):
        services.cancel_lesson(actor=admin_a, lesson=lesson, reason="x")
    assert Attendance.objects.count() == 1
