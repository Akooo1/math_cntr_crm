"""Returning the lessons not taken when a student leaves (owner's request, SPEC §24).
Clock: Monday 16.11.2026 10:00 Tashkent (billing helpers)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.billing import selectors, services
from apps.billing.models import Payment, PaymentMethod
from apps.billing.tests.helpers import D, cash, clock, group, monthly  # noqa: F401
from apps.core.system_settings import set_settings
from apps.salaries import selectors as salaries
from apps.students import services as st
from tests.factories import UserFactory, make_student, page_text

pytestmark = pytest.mark.django_db


@pytest.fixture
def left(clock, admin_a, director, branch_a, group, cash):  # noqa: F811
    set_settings({"salaries.start_month": 202611}, actor=director)
    s = make_student(admin_a, branch_a)
    e = st.enroll(actor=admin_a, student=s, group=group, start_date=D(2026, 11, 2))
    services.payments.record_payment(
        actor=admin_a, student=s, amount=450_000, method=cash, paid_on=D(2026, 11, 16)
    )
    st.leave(actor=admin_a, enrollment=e, end_date=D(2026, 11, 9), reason="ko'chdi")
    e.refresh_from_db()
    return s, e


def test_admin_returns_the_lessons_not_taken_once(left, admin_a, cash):  # noqa: F811
    s, e = left
    assert services.payments.leave_refundable(e) == 346_000  # 450 000 paid, 104 000 used
    with pytest.raises(ValidationError):
        services.payments.refund_on_leave(actor=admin_a, enrollment=e, amount=346_001, method=cash)
    row = services.payments.refund_on_leave(
        actor=admin_a, enrollment=e, amount=346_000, method=cash
    )
    assert row.kind == Payment.Kind.REFUND and row.for_enrollment == e
    assert selectors.balance(s.pk) == 0 and services.payments.leave_refundable(e) == 0
    with pytest.raises(ValidationError):
        services.payments.refund_on_leave(actor=admin_a, enrollment=e, amount=1, method=cash)


def test_teacher_share_counts_only_the_lessons_taken(left, group):  # noqa: F811
    _s, _e = left
    lines = [d for d in salaries.draft(D(2026, 11, 1)) if d.group_id == group.pk]
    assert sum(d.base for d in lines) == 104_000  # not the 450 000 paid at first


def test_absences_are_not_returned(clock, admin_a, branch_a, group, cash):  # noqa: F811
    s = make_student(admin_a, branch_a)
    e = st.enroll(actor=admin_a, student=s, group=group, start_date=D(2026, 11, 2))
    services.payments.record_payment(
        actor=admin_a, student=s, amount=450_000, method=cash, paid_on=D(2026, 11, 16)
    )
    for lesson in group.lessons.filter(date__gte=D(2026, 11, 2), date__lte=D(2026, 11, 13)):
        st.mark_attendance(actor=admin_a, lesson=lesson, student_id=s.pk, status="absent")
    assert services.payments.leave_refundable(e) == 0  # still studying: nothing to return


def test_rules(left, branch_b, manager_a, cash):  # noqa: F811
    _s, e = left
    with pytest.raises(PermissionDenied):
        services.payments.refund_on_leave(actor=manager_a, enrollment=e, amount=1, method=cash)
    online = PaymentMethod.objects.create(name="Onlayn", included_in_cash_close=False)
    from apps.core.roles import Role

    admin_b = UserFactory(role=Role.BRANCH_ADMIN, branches=[branch_b])
    from django.http import Http404

    with pytest.raises(Http404):
        services.payments.refund_on_leave(actor=admin_b, enrollment=e, amount=1, method=cash)
    with pytest.raises(ValidationError):
        services.payments.refund_on_leave(
            actor=UserFactory(role=Role.DIRECTOR), enrollment=e, amount=1, method=online
        )


def test_screens(left, login, admin_a, cash):  # noqa: F811
    s, e = left
    c = login(admin_a)
    assert f"/chiqish/{e.pk}/pul-qaytarish/" in c.get(f"/oquvchilar/{s.pk}/").content.decode()
    resp = c.post(f"/chiqish/{e.pk}/pul-qaytarish/", {"amount": "346 000", "method": cash.pk})
    assert resp.status_code == 302
    assert c.get(f"/chiqish/{e.pk}/pul-qaytarish/").status_code == 404  # nothing left
    receipt = page_text(c.get(resp["Location"]))
    assert "346" in receipt and "000" in receipt  # the receipt
