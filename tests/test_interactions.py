"""Interaction helpers: undo toasts, quick actions on student cards, the payment success
screen and "Everyone came" in attendance (CLAUDE.md, UI kit)."""

import datetime as dt

import pytest
import time_machine
from django.utils import timezone

from apps.billing.models import PaymentMethod
from apps.core.roles import Role
from apps.core.templatetags.mm import undo_url
from apps.crm import services as crm
from apps.crm.models import FollowUpTask
from apps.students import services as st
from apps.telegram.models import Chat
from tests.factories import UserFactory, make_group, make_lead, make_student, page_text

pytestmark = pytest.mark.django_db
NOW = dt.datetime(2026, 11, 16, 5, 0, tzinfo=dt.UTC)  # Monday 10:00 Tashkent


@pytest.fixture(autouse=True)
def clock():
    with time_machine.travel(NOW, tick=False):
        yield


def test_undo_url_accepts_same_site_paths_only():
    assert undo_url("undo:/vazifalar/5/qayta-ochish/") == "/vazifalar/5/qayta-ochish/"
    assert undo_url("undo://evil.example/x") == ""
    assert undo_url("undo:https://evil.example/") == ""
    assert undo_url("") == "" and undo_url(None) == ""


class TestTaskUndo:
    def test_done_then_undo(self, login, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        task = crm.create_task(
            actor=manager_a, lead=lead, assigned_to=manager_a, due_at=timezone.now(), title="Q"
        )
        c = login(manager_a)
        resp = c.post(f"/vazifalar/{task.pk}/bajarildi/", {"next": "/vazifalar/"}, follow=True)
        text = page_text(resp)
        assert "Vazifa bajarildi." in text and "Ortga qaytarish" in text
        assert f'action="/vazifalar/{task.pk}/qayta-ochish/"' in resp.content.decode()
        task.refresh_from_db()
        assert task.done_at is not None

        resp = c.post(f"/vazifalar/{task.pk}/qayta-ochish/", {"next": "/vazifalar/"})
        assert resp.status_code == 302 and resp["Location"] == "/vazifalar/"
        task.refresh_from_db()
        lead.refresh_from_db()
        assert task.done_at is None and task.done_by is None
        assert lead.next_follow_up_at == task.due_at

    def test_reopen_ignores_foreign_next_and_scope(self, login, manager_a, branch_a, branch_b):
        lead = make_lead(manager_a, branch_a)
        task = crm.create_task(
            actor=manager_a, lead=lead, assigned_to=manager_a, due_at=timezone.now(), title="Q"
        )
        crm.complete_task(actor=manager_a, task=task)
        resp = login(manager_a).post(
            f"/vazifalar/{task.pk}/qayta-ochish/", {"next": "//evil.example/"}
        )
        assert resp["Location"] == "/vazifalar/"
        crm.complete_task(actor=manager_a, task=task)
        admin_b = UserFactory(role=Role.BRANCH_ADMIN, branches=[branch_b])
        assert login(admin_b).post(f"/vazifalar/{task.pk}/qayta-ochish/").status_code == 404
        assert FollowUpTask.objects.get(pk=task.pk).done_at is not None


class TestStudentCardActions:
    def _cards(self, client):
        return client.get("/oquvchilar/").content.decode()

    def test_by_role(self, login, admin_a, manager_a, branch_a):
        s = make_student(admin_a, branch_a, parent_phone="+998901112233")
        pay = f"/tolovlar/yangi/?oquvchi={s.pk}"
        admin_html = self._cards(login(admin_a))
        assert 'href="tel:+998901112233"' in admin_html and pay in admin_html
        manager_html = self._cards(login(manager_a))
        assert 'href="tel:+998901112233"' in manager_html and pay not in manager_html

    def test_telegram_only_when_parent_connected(self, login, admin_a, director, branch_a):
        s = make_student(admin_a, branch_a, parent_phone="+998901112244")
        msg = f"/ota-onalarga-xabar/?oquvchi={s.pk}"
        assert msg not in self._cards(login(director))
        Chat.objects.create(
            chat_id=777, kind=Chat.Kind.PARENT, phone="+998901112244", connected_at=timezone.now()
        )
        assert msg in self._cards(login(director))
        assert msg not in self._cards(login(admin_a))  # only the Direktor sends messages


def test_payment_success_screen(login, admin_a, director, branch_a):
    s = make_student(admin_a, branch_a)
    cash = PaymentMethod.objects.get(name="Naqd")
    c = login(admin_a)
    resp = c.post(
        "/tolovlar/yangi/",
        {"student": s.pk, "amount": "250 000", "method": cash.pk, "paid_on": "16.11.2026"},
    )
    assert resp.status_code == 302 and resp["Location"].endswith("?yangi=1")
    text = page_text(c.get(resp["Location"]))
    assert "To'lov qabul qilindi" in text and "Yana to'lov qabul qilish" in text
    assert "250\u202f000\u202fso'm" in text and "avans" in text
    # Someone else opening the same link sees the plain payment page.
    assert "To'lov qabul qilindi" not in page_text(login(director).get(resp["Location"]))


def test_everyone_came_button(login, admin_a, branch_a, teacher_a):
    group = make_group(admin_a, branch_a, teacher=teacher_a, start=dt.date(2026, 9, 1))
    s = make_student(admin_a, branch_a)
    st.enroll(actor=admin_a, student=s, group=group, start_date=dt.date(2026, 9, 1))
    lesson = group.lessons.filter(date__lte=dt.date(2026, 11, 16)).order_by("-date").first()
    text = page_text(login(teacher_a).get(f"/davomat/{lesson.pk}/"))
    assert "Hammasi keldi" in text
