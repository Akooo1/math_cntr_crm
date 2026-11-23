import datetime as dt

import pytest
import time_machine
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404

from apps.core.models import AuditLog, OutboxEvent
from apps.students import extensions, selectors, services
from apps.students.models import Enrollment, EnrollmentEvent
from tests.factories import make_group, make_student

pytestmark = pytest.mark.django_db
D = dt.date


@pytest.fixture(autouse=True)
def frozen_clock():
    with time_machine.travel(dt.datetime(2026, 10, 15, 9, 0, tzinfo=dt.UTC), tick=False):
        yield


@pytest.fixture
def group(admin_a, branch_a):
    return make_group(admin_a, branch_a, start=D(2026, 9, 1), end=D(2027, 5, 31), capacity=2)


@pytest.fixture
def student(admin_a, branch_a):
    return make_student(admin_a, branch_a)


class TestEnroll:
    def test_enroll_records_event_audit_and_outbox(self, admin_a, group, student):
        e = services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 10, 1))
        assert e.status == Enrollment.Status.ACTIVE
        assert e.events.get().kind == EnrollmentEvent.Kind.ENROLLED
        assert AuditLog.objects.filter(action="students.enrollment.create").exists()
        assert OutboxEvent.objects.filter(event_type="students.enrollment_created").exists()

    def test_rules(self, admin_a, branch_b, director, group, student):
        with pytest.raises(ValidationError):  # before the group starts
            services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 8, 31))
        services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 9, 1))
        with pytest.raises(ValidationError):  # already in the group
            services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 10, 1))
        other = make_group(director, branch_b)
        with pytest.raises((ValidationError, Http404)):  # other branch
            services.enroll(actor=director, student=student, group=other, start_date=D(2026, 10, 1))

    def test_capacity_needs_override(self, admin_a, branch_a, group):
        for _ in range(2):
            services.enroll(
                actor=admin_a,
                student=make_student(admin_a, branch_a),
                group=group,
                start_date=D(2026, 9, 1),
            )
        third = make_student(admin_a, branch_a)
        with pytest.raises(ValidationError):
            services.enroll(actor=admin_a, student=third, group=group, start_date=D(2026, 9, 1))
        services.enroll(
            actor=admin_a,
            student=third,
            group=group,
            start_date=D(2026, 9, 1),
            capacity_override=True,
        )
        entry = AuditLog.objects.filter(action="students.enrollment.create").first()  # newest
        assert entry.after["over_capacity"] is True

    def test_manager_and_teacher_cannot_enroll(self, manager_a, teacher_a, group, student):
        for user in (manager_a, teacher_a):
            with pytest.raises(PermissionDenied):
                services.enroll(actor=user, student=student, group=group, start_date=D(2026, 10, 1))


class TestLifecycle:
    def test_move_closes_old_and_opens_new(self, admin_a, branch_a, group, student):
        old = services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 9, 1))
        target = make_group(admin_a, branch_a, start=D(2026, 9, 1))
        new = services.move(
            actor=admin_a,
            enrollment=old,
            target_group=target,
            effective_date=D(2026, 10, 12),
            reason="vaqt",
        )
        old.refresh_from_db()
        assert old.status == Enrollment.Status.MOVED and old.end_date == D(2026, 10, 12)
        assert new.group == target and new.start_date == D(2026, 10, 12)
        out = old.events.get(kind="moved_out")
        assert out.related_enrollment == new and out.reason == "vaqt"
        assert new.events.get(kind="moved_in").related_enrollment == old

    def test_reason_is_required(self, admin_a, group, student):
        e = services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 9, 1))
        for call in (
            lambda: services.freeze(
                actor=admin_a, enrollment=e, from_date=D(2026, 10, 1), reason=""
            ),
            lambda: services.leave(
                actor=admin_a, enrollment=e, end_date=D(2026, 10, 1), reason=" "
            ),
        ):
            with pytest.raises(ValidationError):
                call()

    def test_freeze_unfreeze_and_roster(self, admin_a, group, student):
        e = services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 9, 1))
        services.freeze(actor=admin_a, enrollment=e, from_date=D(2026, 10, 5), reason="kasal")
        e.refresh_from_db()
        assert e.status == Enrollment.Status.FROZEN
        with pytest.raises(ValidationError):  # can't move a frozen enrollment
            services.move(
                actor=admin_a,
                enrollment=e,
                target_group=group,
                effective_date=D(2026, 10, 6),
                reason="x",
            )
        services.unfreeze(
            actor=admin_a, enrollment=e, effective_date=D(2026, 10, 19), reason="sog'aydi"
        )
        e.refresh_from_db()
        freeze = e.freezes.get()
        assert e.status == Enrollment.Status.ACTIVE and freeze.to_date == D(2026, 10, 19)

        def on(day):
            lesson = group.lessons.filter(date=day).first()
            return [x.student_id for x in selectors.roster(lesson)]

        assert on(D(2026, 10, 2)) == [student.pk]  # Fri before the freeze
        assert on(D(2026, 10, 9)) == []  # frozen
        assert on(D(2026, 10, 19)) == [student.pk]  # back (Mon)

    def test_leave_end_date_is_exclusive(self, admin_a, group, student):
        e = services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 9, 1))
        services.leave(actor=admin_a, enrollment=e, end_date=D(2026, 10, 7), reason="ko'chdi")
        e.refresh_from_db()
        assert e.status == Enrollment.Status.LEFT and e.end_date == D(2026, 10, 7)
        mon = group.lessons.get(date=D(2026, 10, 5))
        wed = group.lessons.get(date=D(2026, 10, 7))
        assert selectors.roster(mon) and not selectors.roster(wed)
        with pytest.raises(ValidationError):
            services.leave(actor=admin_a, enrollment=e, end_date=D(2026, 10, 9), reason="x")

    def test_student_status_is_derived(self, admin_a, group, student):
        assert selectors.student_status(student) == "new"
        e = services.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 9, 1))
        assert selectors.student_status(student) == "active"
        services.leave(actor=admin_a, enrollment=e, end_date=D(2026, 10, 1), reason="x")
        assert selectors.student_status(student) == "left"


class FakeBilling:
    """Stands in for the billing extension that arrives in phase 4."""

    key = "fake"
    template = "components/form_errors.html"

    def __init__(self):
        self.applied = []

    def preview(self, action):
        return {"kind": action.kind}

    def validate(self, action, data):
        return [] if data.get("ok") == "1" else ["xato"]

    def apply(self, action, data, *, actor, result):
        self.applied.append((action.kind, result.enrollment.pk, data is not None))


@pytest.fixture
def fake_extension():
    ext = FakeBilling()
    extensions.register(ext)
    yield ext
    extensions._extensions.pop(ext.key)


def test_extensions_run_in_the_same_transaction(admin_a, group, student, fake_extension):
    with pytest.raises(ValidationError):
        services.enroll(
            actor=admin_a,
            student=student,
            group=group,
            start_date=D(2026, 9, 1),
            extension_data={"ok": "0"},
        )
    assert not Enrollment.objects.exists()  # rolled back
    e = services.enroll(
        actor=admin_a,
        student=student,
        group=group,
        start_date=D(2026, 9, 1),
        extension_data={"ok": "1"},
    )
    services.leave(actor=admin_a, enrollment=e, end_date=D(2026, 10, 1), reason="x")
    assert fake_extension.applied == [("enroll", e.pk, True), ("leave", e.pk, False)]


def test_import_skips_extensions(admin_a, group, student, fake_extension):
    services.enroll(
        actor=admin_a, student=student, group=group, start_date=D(2026, 9, 1), skip_extensions=True
    )
    assert fake_extension.applied == []


def test_enroll_view_shows_confirmation_step(login, admin_a, group, student, fake_extension):
    c = login(admin_a)
    url = f"/oquvchilar/{student.pk}/guruhga-qoshish/"
    data = {"group": group.pk, "date": "01.09.2026", "reason": ""}
    step = c.post(url, data)
    assert step.status_code == 200 and 'name="tasdiq"' in step.content.decode()
    assert not Enrollment.objects.exists()
    resp = c.post(url, {**data, "tasdiq": "1", "ok": "1"})
    assert resp.status_code == 302
    assert Enrollment.objects.count() == 1
