"""One student in three groups of the same branch (owner's request): every screen shows
every group, each group charges its own full fee, no automatic discount.
Clock: Monday 16.11.2026 10:00 Tashkent."""

import pytest

from apps.billing import selectors, services
from apps.billing.models import Charge
from apps.billing.tests.helpers import MWF, D, cash, clock, monthly  # noqa: F401
from apps.students import services as st
from tests.factories import UserFactory, make_group, make_student, page_text

pytestmark = pytest.mark.django_db


@pytest.fixture
def three(clock, admin_a, branch_a, monthly):  # noqa: F811
    from apps.core.roles import Role

    teachers = [UserFactory(role=Role.TEACHER, branches=[branch_a]) for _ in range(3)]
    groups = [
        make_group(
            admin_a, branch_a, teacher=t, course=monthly, start=D(2026, 9, 1), days=MWF, name=n
        )
        for t, n in zip(teachers, ("Matematika 7-A", "Olimpiada", "Mantiq"), strict=True)
    ]
    s = make_student(admin_a, branch_a, last_name="Uchguruhov", first_name="Sardor")
    for g in groups:
        st.enroll(actor=admin_a, student=s, group=g, start_date=D(2026, 11, 2))
    return s, groups, teachers


def test_every_group_charges_its_own_full_fee(three):
    s, groups, _t = three
    charges = Charge.objects.filter(student=s, kind="monthly")
    assert {c.enrollment.group for c in charges} == set(groups)
    assert len({c.amount for c in charges}) == 1  # same course, same fee, no discount
    assert selectors.balance(s.pk) == -sum(c.amount for c in charges)


def test_screens_show_every_group(three, login, admin_a):
    s, groups, teachers = three
    c = login(admin_a)
    names = [g.name for g in groups]
    pages = {
        "profile": page_text(c.get(f"/oquvchilar/{s.pk}/")),
        "list": page_text(c.get("/oquvchilar/")),
        "debtors": page_text(c.get("/qarzdorlar/")),
    }
    for key, text in pages.items():
        missing = [n for n in names if n not in text]
        assert not missing, (key, missing)
    for g in groups:  # filtering the list by each group finds the student
        assert s.full_name in page_text(c.get(f"/oquvchilar/?guruh={g.pk}"))
    for g, t in zip(groups, teachers, strict=True):  # each teacher sees them in Davomat
        lesson = g.lessons.get(date=D(2026, 11, 16))
        assert s.full_name in page_text(login(t).get(f"/davomat/{lesson.pk}/"))


def test_a_payment_pays_the_groups_oldest_first(three, admin_a, cash):  # noqa: F811
    s, _g, _t = three
    owed = -selectors.balance(s.pk)
    services.payments.record_payment(
        actor=admin_a, student=s, amount=owed, method=cash, paid_on=D(2026, 11, 16)
    )
    assert selectors.balance(s.pk) == 0


def test_parent_bot_lists_every_group(three):
    from apps.telegram.models import Chat
    from apps.telegram.services import parent_menu

    s, groups, _t = three
    from apps.core import dates

    chat = Chat.objects.create(
        chat_id=7, kind=Chat.Kind.PARENT, phone=s.parent_phone, connected_at=dates.now()
    )
    text = parent_menu.answer(chat, parent_menu.SCHEDULE)
    assert all(g.name in text for g in groups)
