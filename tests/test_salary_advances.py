"""Maosh avansi and payouts from the Kassa (owner's request, docs/SPEC.md §24).
Clock: Monday 16.11.2026 10:00 Tashkent (billing helpers)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.billing.services.cash import close_day, day_report
from apps.billing.tests.helpers import D, cash, clock  # noqa: F401
from apps.core.system_settings import set_settings
from apps.salaries import selectors, services
from apps.salaries.models import Adjustment, Advance
from tests.factories import page_text

pytestmark = pytest.mark.django_db
TODAY = D(2026, 11, 16)
NOV = D(2026, 11, 1)


@pytest.fixture
def paid_staff(clock, director, admin_a):  # noqa: F811
    set_settings({"salaries.start_month": 202611}, actor=director)
    services.set_staff_pay(actor=director, user=admin_a, amount=3_000_000, effective_from=NOV)
    return admin_a


def give(director, person, amount, branch, method, day=TODAY):
    return services.give_advance(
        actor=director, person=person, amount=amount, given_on=day, branch=branch, method=method
    )


def salaries_out(branch, day=TODAY):
    src = next(s for s in day_report(branch.pk, day)["sources"] if s["code"] == "salaries")
    return src["out"], src["in"]


def test_advance_comes_out_of_the_kassa_and_off_the_salary(
    paid_staff,
    director,
    branch_a,
    cash,  # noqa: F811
):
    give(director, paid_staff, 1_000_000, branch_a, cash)
    assert salaries_out(branch_a) == (1_000_000, 0)
    sheet = selectors.sheet(director, paid_staff.pk, NOV)
    assert (sheet.totals.total, sheet.totals.advances, sheet.totals.to_pay) == (
        3_000_000,
        1_000_000,
        2_000_000,
    )
    with pytest.raises(ValidationError):  # more than earned so far
        give(director, paid_staff, 2_000_001, branch_a, cash)
    give(director, paid_staff, 2_000_000, branch_a, cash)


def test_cancel_puts_the_money_back(paid_staff, director, branch_a, cash):  # noqa: F811
    a = give(director, paid_staff, 500_000, branch_a, cash)
    services.cancel_advance(actor=director, advance=a, reason="xato")
    assert salaries_out(branch_a) == (500_000, 500_000)
    assert selectors.sheet(director, paid_staff.pk, NOV).totals.advances == 0
    with pytest.raises(ValidationError):
        services.cancel_advance(actor=director, advance=a, reason="yana")


def test_month_end_pays_the_rest_from_the_kassa(paid_staff, director, branch_a, cash):  # noqa: F811
    give(director, paid_staff, 1_000_000, branch_a, cash)
    services.close_month(actor=director, month=NOV)
    payout = services.pay_out(
        actor=director, teacher=paid_staff, month=NOV, paid_on=TODAY, branch=branch_a, method=cash
    )
    assert payout.amount == 2_000_000
    assert salaries_out(branch_a) == (3_000_000, 0)
    with pytest.raises(ValidationError):  # the Kassa needs a branch and method
        services.pay_out(actor=director, teacher=paid_staff, month=NOV, paid_on=TODAY)
    services.cancel_payout(actor=director, payout=payout, reason="xato")
    assert salaries_out(branch_a) == (3_000_000, 2_000_000)


def test_advances_above_a_lowered_total_carry_into_next_month(
    paid_staff,
    director,
    branch_a,
    cash,  # noqa: F811
):
    give(director, paid_staff, 2_000_000, branch_a, cash)
    services.add_adjustment(
        actor=director,
        teacher=paid_staff,
        month=NOV,
        kind="deduction",
        amount=1_500_000,
        reason="ishlamadi",
    )
    services.close_month(actor=director, month=NOV)
    carry = Adjustment.objects.get(kind=Adjustment.Kind.CARRY)
    assert (carry.month, carry.amount) == (D(2026, 12, 1), -500_000)


def test_rules(paid_staff, director, admin_a, teacher_a, branch_a, cash):  # noqa: F811
    with pytest.raises(PermissionDenied):
        give(admin_a, paid_staff, 1000, branch_a, cash)
    with pytest.raises(ValidationError):  # a teacher with no money paid has earned nothing
        give(director, teacher_a, 1000, branch_a, cash)
    from apps.billing.models import PaymentMethod

    online = PaymentMethod.objects.create(name="Onlayn", included_in_cash_close=False)
    with pytest.raises(ValidationError):
        give(director, paid_staff, 1000, branch_a, online)
    close_day(actor=director, branch=branch_a, day=TODAY)
    with pytest.raises(ValidationError):  # a closed Kassa day
        give(director, paid_staff, 1000, branch_a, cash)
    assert not Advance.objects.exists()


def test_screens(paid_staff, director, login, branch_a, cash):  # noqa: F811
    c = login(director)
    url = f"/maosh/oqituvchi/{paid_staff.pk}/"
    c.post(
        f"{url}avans/",
        {
            "oy": "11.2026",
            "amount": "700 000",
            "given_on": "16.11.2026",
            "branch": branch_a.pk,
            "method": cash.pk,
        },
    )
    assert Advance.objects.get().amount == 700_000
    text = page_text(c.get(f"{url}?oy=11.2026")).replace("\u202f", " ")
    assert "700 000" in text and "2 300 000" in text
    kassa = page_text(c.get(f"/kassa/?filial={branch_a.pk}&sana=16.11.2026"))
    assert "700 000" in kassa.replace("\u202f", " ")
