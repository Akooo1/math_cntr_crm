import datetime as dt

import pytest
import time_machine
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.models import AuditLog, OutboxEvent
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


@pytest.fixture
def setup(admin_a, branch_a, teacher_a):
    group = make_group(
        admin_a, branch_a, teacher=teacher_a, start=D(2026, 9, 1), end=D(2026, 12, 31)
    )
    student = make_student(admin_a, branch_a)
    services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 9, 1))
    return group, student


def lesson_on(group, day):
    return group.lessons.get(date=day)


def test_teacher_marks_own_lesson(teacher_a, setup):
    group, student = setup
    lesson = lesson_on(group, D(2026, 10, 14))
    services.mark_attendance(
        actor=teacher_a, lesson=lesson, student_id=student.pk, status="present"
    )
    lesson.refresh_from_db()
    assert lesson.status == Lesson.Status.HELD
    assert OutboxEvent.objects.filter(event_type="students.lesson_held").count() == 1
    services.mark_attendance(actor=teacher_a, lesson=lesson, student_id=student.pk, status="absent")
    assert Attendance.objects.get().status == "absent"
    assert AuditLog.objects.filter(action="students.attendance.update").count() == 1


def test_other_teacher_cannot_mark(branch_a, setup):
    group, student = setup
    other = UserFactory(role=Role.TEACHER, branches=[branch_a])
    with pytest.raises(PermissionDenied):
        services.mark_attendance(
            actor=other,
            lesson=lesson_on(group, D(2026, 10, 14)),
            student_id=student.pk,
            status="present",
        )


def test_manager_cannot_mark(manager_a, setup):
    group, student = setup
    with pytest.raises(PermissionDenied):
        services.mark_attendance(
            actor=manager_a,
            lesson=lesson_on(group, D(2026, 10, 14)),
            student_id=student.pk,
            status="present",
        )


def test_teacher_edit_window_and_future(teacher_a, admin_a, setup):
    group, student = setup
    old = lesson_on(group, D(2026, 10, 2))  # 13 days ago, window is 7
    with pytest.raises(ValidationError):
        services.mark_attendance(
            actor=teacher_a, lesson=old, student_id=student.pk, status="present"
        )
    services.mark_attendance(
        actor=admin_a, lesson=old, student_id=student.pk, status="present"
    )  # admin may
    future = lesson_on(group, D(2026, 10, 16))
    with pytest.raises(ValidationError):
        services.mark_attendance(
            actor=admin_a, lesson=future, student_id=student.pk, status="present"
        )


def test_student_outside_roster_rejected(admin_a, branch_a, setup):
    group, _student = setup
    stranger = make_student(admin_a, branch_a)
    with pytest.raises(ValidationError):
        services.mark_attendance(
            actor=admin_a,
            lesson=lesson_on(group, D(2026, 10, 14)),
            student_id=stranger.pk,
            status="present",
        )


def test_htmx_toggle_returns_row(login, teacher_a, setup):
    group, student = setup
    lesson = lesson_on(group, D(2026, 10, 14))
    c = login(teacher_a)
    resp = c.post(
        f"/davomat/{lesson.pk}/belgilash/",
        {"student": student.pk, "status": "present"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200 and f'id="att-{student.pk}"' in resp.content.decode()
    assert Attendance.objects.get().status == "present"
