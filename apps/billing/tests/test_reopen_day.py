"""Reopening a closed cash day (owner's request, docs/SPEC.md §24).
Clock: Monday 16.11.2026 10:00 Tashkent (billing helpers)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, InternalError, connection, transaction

from apps.billing import services
from apps.billing.models import CashDayClose, CashDayReopen, Payment
from apps.core.models import AuditLog
from apps.students import services as st
from tests.factories import page_text

from .helpers import D

pytestmark = pytest.mark.django_db
TODAY = D(2026, 11, 16)


def pay(actor, student, amount, cash):
    return services.payments.record_payment(
        actor=actor, student=student, amount=amount, method=cash, paid_on=TODAY
    )


@pytest.fixture
def closed(clock, admin_a, director, branch_a, student, group, cash):
    st.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 11, 2))
    pay(admin_a, student, 100_000, cash)
    return services.cash.close_day(actor=director, branch=branch_a, day=TODAY)


def test_reopen_lets_the_day_change_then_close_again(
    closed, admin_a, director, branch_a, student, cash
):
    with pytest.raises(ValidationError):
        pay(admin_a, student, 1000, cash)
    services.cash.reopen_day(actor=director, branch=branch_a, day=TODAY, reason="chek xato")
    pay(admin_a, student, 50_000, cash)  # the service allows it
    with transaction.atomic():  # and so does the database lock
        Payment.objects.create(
            student=student,
            branch=branch_a,
            amount=1,
            method=cash,
            paid_on=TODAY,
            received_by=admin_a,
            receipt_seq=990,
            receipt_number="CH-000990",
        )
    again = services.cash.close_day(actor=director, branch=branch_a, day=TODAY)
    assert again.totals["total_in"] == 150_001 and closed.totals["total_in"] == 100_000
    assert CashDayClose.objects.filter(branch=branch_a, date=TODAY).count() == 2
    with pytest.raises(ValidationError):  # locked again
        pay(admin_a, student, 1000, cash)
    with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
        Payment.objects.create(
            student=student,
            branch=branch_a,
            amount=1,
            method=cash,
            paid_on=TODAY,
            received_by=admin_a,
            receipt_seq=991,
            receipt_number="CH-000991",
        )
    assert AuditLog.objects.filter(action="billing.cash_day.reopen", reason="chek xato").exists()


def test_rules(closed, admin_a, director, branch_a):
    with pytest.raises(PermissionDenied):
        services.cash.reopen_day(actor=admin_a, branch=branch_a, day=TODAY, reason="x")
    with pytest.raises(ValidationError):
        services.cash.reopen_day(actor=director, branch=branch_a, day=TODAY, reason="  ")
    with pytest.raises(ValidationError):  # an open day
        services.cash.reopen_day(actor=director, branch=branch_a, day=D(2026, 11, 15), reason="x")
    services.cash.reopen_day(actor=director, branch=branch_a, day=TODAY, reason="x")
    with pytest.raises(ValidationError):  # already open
        services.cash.reopen_day(actor=director, branch=branch_a, day=TODAY, reason="x")
    with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM billing_cash_day_reopen")
    assert CashDayReopen.objects.count() == 1


def test_screen(closed, login, admin_a, director, branch_a):
    url = f"/kassa/?filial={branch_a.pk}&sana=16.11.2026"
    assert "qayta-ochish" not in login(admin_a).get(url).content.decode()
    c = login(director)
    assert "qayta-ochish" in c.get(url).content.decode()
    c.post("/kassa/qayta-ochish/", {"filial": branch_a.pk, "sana": "16.11.2026", "reason": "xato"})
    page = c.get(url)
    assert page.context["closed"] is None and "xato" in page_text(page)
