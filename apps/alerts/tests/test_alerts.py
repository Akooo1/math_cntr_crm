"""Early warnings end to end (docs/SPEC.md §19). Clock: Monday 16.11.2026 10:00 Tashkent."""

import datetime as dt

import pytest

from apps.alerts import selectors, services
from apps.alerts.models import Task
from apps.billing import services as billing
from apps.billing.tests.helpers import MWF
from apps.core.system_settings import set_settings
from apps.crm import services as crm
from apps.students import services as st
from apps.students.models import EnrollmentEvent, LeaveReason
from apps.telegram import client as tg
from apps.telegram.models import Chat, Message
from tests.factories import make_group, make_lead, make_student, page_text

pytestmark = pytest.mark.django_db
D = dt.date


def at(clock, day, hh, mm=0):
    clock.move_to(dt.datetime(day.year, day.month, day.day, hh - 5, mm, tzinfo=dt.UTC))


@pytest.fixture
def lessons(clock, admin_a, branch_a, teacher_a):
    g = make_group(admin_a, branch_a, teacher=teacher_a, start=D(2026, 9, 1), days=MWF)
    s = make_student(admin_a, branch_a)
    st.enroll(actor=admin_a, student=s, group=g, start_date=D(2026, 9, 1))
    return g, s


def mark(actor, g, s, day, status):
    lesson = g.lessons.get(date=day)
    st.mark_attendance(actor=actor, lesson=lesson, student_id=s.pk, status=status)


class TestAbsences:
    def test_streak_makes_one_task_then_resolves(self, lessons, admin_a, manager_a, teacher_a):
        g, s = lessons
        mark(admin_a, g, s, D(2026, 11, 9), "present")
        mark(admin_a, g, s, D(2026, 11, 11), "absent")
        assert services.run_checks()["absence"] == 0  # one missed lesson is not a streak
        mark(admin_a, g, s, D(2026, 11, 13), "absent")
        assert services.run_checks()["absence"] == 1
        assert services.run_checks()["absence"] == 0  # idempotent
        task = Task.objects.get(kind=Task.Kind.ABSENCE)
        assert (task.student, task.group, task.assigned_to, task.details["missed"]) == (
            s,
            g,
            None,
            2,
        )
        assert selectors.counts(admin_a)["absence"] == 1
        assert selectors.counts(manager_a)["total"] == 0
        assert selectors.counts(teacher_a)["total"] == 0  # given to administrators
        mark(admin_a, g, s, D(2026, 11, 16), "absent")  # streak grows: same task, new count
        services.run_checks()
        task.refresh_from_db()
        assert task.details["missed"] == 3
        assert Task.objects.filter(kind=Task.Kind.ABSENCE).count() == 1
        mark(admin_a, g, s, D(2026, 11, 16), "present")
        services.run_checks()
        task.refresh_from_db()
        assert task.closed_how == Task.Closed.RESOLVED

    def test_to_teacher_and_switched_off(self, lessons, admin_a, director, teacher_a):
        g, s = lessons
        set_settings({"alerts.absence_assignee": 2}, actor=director)
        mark(admin_a, g, s, D(2026, 11, 11), "absent")
        mark(admin_a, g, s, D(2026, 11, 13), "absent")
        services.run_checks()
        assert Task.objects.get(kind=Task.Kind.ABSENCE).assigned_to == teacher_a
        assert selectors.counts(teacher_a)["absence"] == 1
        Task.objects.all().delete()
        set_settings({"alerts.absence_streak": 0}, actor=director)
        assert services.run_checks()["absence"] == 0


class TestDebts:
    def test_overdue_debt_task_repeat_and_payment(
        self, clock, admin_a, manager_a, branch_a, group, cash
    ):
        s = make_student(admin_a, branch_a)
        st.enroll(actor=admin_a, student=s, group=group, start_date=D(2026, 10, 1))  # due 01.10
        assert services.run_checks()["debt"] == 1
        task = Task.objects.get(kind=Task.Kind.DEBT)
        assert task.details["days"] == 46 and task.details["overdue"] > 0
        assert selectors.counts(manager_a)["debt"] == 0  # money never reaches managers
        services.close(actor=admin_a, task=task)
        assert services.run_checks()["debt"] == 0  # same round, already handled
        clock.move_to(dt.datetime(2026, 11, 23, 5, 0, tzinfo=dt.UTC))
        assert services.run_checks()["debt"] == 1  # still unpaid a week later
        from apps.billing.selectors import balance

        billing.payments.record_payment(
            actor=admin_a, student=s, amount=-balance(s.pk), method=cash, paid_on=D(2026, 11, 23)
        )
        services.run_checks()
        assert not Task.objects.filter(kind=Task.Kind.DEBT, closed_at__isnull=True).exists()


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def call(self, method, **params):
        return True

    def send(self, chat_id, text, **extra):
        self.sent.append((chat_id, text))
        return {}


class TestLeads:
    def test_deadline_telegram_and_contact(self, clock, manager_a, branch_a, settings):
        settings.TELEGRAM_BOT_TOKEN = "123:TEST"
        fake = FakeTelegram()
        tg.set_client(fake)
        try:
            Chat.objects.create(
                chat_id=55,
                kind=Chat.Kind.STAFF,
                user=manager_a,
                connected_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
            )
            at(clock, D(2026, 11, 16), 18, 30)
            lead = make_lead(manager_a, branch_a, manager=manager_a)
            at(clock, D(2026, 11, 16), 21, 0)
            assert services.run_checks()["lead"] == 0  # due 10:30 tomorrow (working hours)
            at(clock, D(2026, 11, 17), 10, 31)
            with django_capture_on_commit():
                assert services.run_checks()["lead"] == 1
            task = Task.objects.get(kind=Task.Kind.LEAD)
            assert task.assigned_to == manager_a and task.lead == lead
            assert (
                fake.sent
                and fake.sent[0][0] == 55
                and lead.phone[-4:] in fake.sent[0][1].replace(" ", "")
            )
            assert Message.objects.filter(kind=Message.Kind.ALERT).exists()
            crm.add_activity(actor=manager_a, lead=lead, kind="call", text="gaplashdik")
            services.run_checks()
            task.refresh_from_db()
            assert task.closed_how == Task.Closed.RESOLVED
        finally:
            tg.set_client(None)


def django_capture_on_commit():
    """Run transaction.on_commit callbacks inside the test transaction."""
    from django.test import TestCase

    return TestCase.captureOnCommitCallbacks(execute=True)


class TestScreens:
    def test_list_done_and_undo(self, lessons, admin_a, login):
        g, s = lessons
        mark(admin_a, g, s, D(2026, 11, 11), "absent")
        mark(admin_a, g, s, D(2026, 11, 13), "absent")
        services.run_checks()
        task = Task.objects.get(kind=Task.Kind.ABSENCE)
        c = login(admin_a)
        text = page_text(c.get("/ogohlantirishlar/"))
        assert "Ketma-ket 2 ta dars qoldirdi" in text and s.full_name in text
        assert "Ogohlantirishlar" in page_text(c.get("/"))  # dashboard tile
        resp = c.post(
            f"/ogohlantirishlar/{task.pk}/bajarildi/", {"next": "/ogohlantirishlar/"}, follow=True
        )
        assert "Ortga qaytarish" in page_text(resp)
        task.refresh_from_db()
        assert task.closed_how == Task.Closed.DONE
        c.post(f"/ogohlantirishlar/{task.pk}/qayta-ochish/")
        task.refresh_from_db()
        assert task.closed_at is None

    def test_other_branch_cannot_close(self, lessons, admin_a, login, branch_b):
        from apps.core.roles import Role
        from tests.factories import UserFactory

        g, s = lessons
        mark(admin_a, g, s, D(2026, 11, 11), "absent")
        mark(admin_a, g, s, D(2026, 11, 13), "absent")
        services.run_checks()
        task = Task.objects.get(kind=Task.Kind.ABSENCE)
        other = UserFactory(role=Role.BRANCH_ADMIN, branches=[branch_b])
        assert login(other).post(f"/ogohlantirishlar/{task.pk}/bajarildi/").status_code == 404


class TestLeaveReasons:
    def test_leave_with_reason_and_report(self, lessons, admin_a, login):
        from apps.core.reports import Params, get_report

        g, s = lessons
        e = s.enrollments.get()
        reason = LeaveReason.objects.get(name="Narxi qimmat")
        c = login(admin_a)
        data = {"date": "16.11.2026", "leave_reason": reason.pk, "reason": ""}
        resp = c.post(_leave_url(e), data)
        if resp.status_code == 200:  # billing asks to confirm the last charge first
            assert "Ketish sababi" in page_text(resp) or "Tasdiqlash" in page_text(resp)
            resp = c.post(_leave_url(e), {**data, "tasdiq": "1"})
        assert resp.status_code == 302
        event = EnrollmentEvent.objects.get(kind=EnrollmentEvent.Kind.LEFT)
        assert event.leave_reason == reason and event.reason == "Narxi qimmat"
        result = get_report("ketish-sabablari").build(
            admin_a, Params(D(2026, 11, 1), D(2026, 11, 30), None)
        )
        assert result.rows == [["Narxi qimmat", 1, 1.0]]

    def test_inactive_reason_refused(self, lessons, admin_a):
        from django.core.exceptions import ValidationError

        g, s = lessons
        reason = LeaveReason.objects.create(name="Eski", is_active=False)
        with pytest.raises(ValidationError):
            st.leave(
                actor=admin_a,
                enrollment=s.enrollments.get(),
                end_date=D(2026, 11, 16),
                leave_reason=reason,
            )


def _leave_url(enrollment):
    from django.urls import reverse

    return reverse("students:leave", args=[enrollment.pk])
