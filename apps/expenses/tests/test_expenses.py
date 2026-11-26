"""Expenses, staff salaries and branch profit (docs/SPEC.md §20).
Clock: Monday 16.11.2026 10:00 Tashkent (billing test helpers)."""

import datetime as dt
from fractions import Fraction

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404

from apps.billing import services as billing
from apps.billing.domain.rounding import round_amount
from apps.billing.services.cash import close_day, day_report
from apps.core.models import AuditLog
from apps.core.reports import Params, get_report
from apps.core.roles import Role
from apps.core.system_settings import set_settings
from apps.expenses import domain, selectors, services
from apps.expenses.models import Category, Expense
from apps.salaries import selectors as salary_selectors
from apps.salaries import services as salaries
from apps.salaries.models import FixedLine
from apps.students import services as st
from tests.factories import UserFactory, make_student, page_text

pytestmark = pytest.mark.django_db
D = dt.date
TODAY = D(2026, 11, 16)


def rent():
    return Category.objects.get(name="Ijara")


def spend(actor, branch, amount, *, cash=None, day=TODAY):
    return services.record(
        actor=actor, branch=branch, category=rent(), amount=amount, spent_on=day, method=cash
    )


# --- pure split ------------------------------------------------------------------------------


def test_split_adds_up_and_follows_weights():
    parts = domain.split(1_000_000, {1: 2_000_000, 2: 1_000_000}, round_amount)
    assert parts == {1: 666_667, 2: 333_333} and sum(parts.values()) == 1_000_000
    assert domain.split(100, {1: 0, 2: 0, 3: 0}, round_amount) == {1: 34, 2: 33, 3: 33}
    assert domain.split(0, {1: 5}, round_amount) == {1: 0}
    assert domain.split(10, {}, round_amount) == {}
    assert domain.split(7, {1: -5, 2: 3}, round_amount) == {1: 0, 2: 7}
    assert isinstance(Fraction(1, 3), Fraction)


# --- expenses and the Kassa ------------------------------------------------------------------


class TestExpenses:
    def test_cash_expense_lowers_kassa_and_closed_day_blocks(self, clock, admin_a, branch_a, cash):
        e = spend(admin_a, branch_a, 200_000, cash=cash)
        report = day_report(branch_a.pk, TODAY)
        naqd = next(b for b in report["methods"] if b["method"] == cash)
        assert naqd["out"] == 200_000 and naqd["net"] == -200_000
        source = next(s for s in report["sources"] if s["code"] == "expenses")
        assert source["out"] == 200_000
        assert AuditLog.objects.filter(action="expenses.expense.create").exists()
        close_day(actor=admin_a, branch=branch_a, day=TODAY)
        with pytest.raises(ValidationError):
            spend(admin_a, branch_a, 1000, cash=cash)
        spend(admin_a, branch_a, 1000)  # not from the cash desk: allowed
        assert e.kind == Expense.Kind.EXPENSE

    def test_rules(self, clock, admin_a, director, branch_a, branch_b, cash):
        with pytest.raises(PermissionDenied):
            spend(admin_a, None, 1000)  # center-wide: Direktor only
        with pytest.raises(Http404):  # another branch
            spend(admin_a, branch_b, 1000)
        with pytest.raises(ValidationError):
            spend(director, None, 1000, cash=cash)  # center-wide can't use a drawer
        with pytest.raises(ValidationError):
            spend(admin_a, branch_a, 1000, day=TODAY + dt.timedelta(days=1))
        with pytest.raises(ValidationError):
            spend(admin_a, branch_a, 0)
        with pytest.raises(ValidationError):
            spend(admin_a, branch_a, 1000, cash=cash, day=D(2026, 9, 1))  # beyond backdating
        spend(director, None, 5000)

    def test_reverse_and_append_only(self, clock, admin_a, director, branch_a, cash):
        e = spend(admin_a, branch_a, 300_000, cash=cash)
        with pytest.raises(PermissionDenied):
            services.reverse(actor=admin_a, expense=e, reason="xato")
        with pytest.raises(ValidationError):
            services.reverse(actor=director, expense=e, reason=" ")
        services.reverse(actor=director, expense=e, reason="xato")
        with pytest.raises(ValidationError):
            services.reverse(actor=director, expense=e, reason="yana")
        assert day_report(branch_a.pk, TODAY)["methods"][0]["net"] == 0
        assert selectors.net_total(Expense.objects.all()) == 0
        with pytest.raises(IntegrityError), transaction.atomic():
            Expense.objects.filter(pk=e.pk).update(amount=1)

    def test_scope(self, clock, admin_a, director, branch_a, branch_b):
        spend(admin_a, branch_a, 1000)
        spend(director, branch_b, 2000)
        spend(director, None, 3000)
        assert selectors.net_total(selectors.expenses_for(admin_a)) == 1000
        assert selectors.net_total(selectors.expenses_for(director)) == 6000


class TestScreens:
    def test_create_list_detail_reverse(self, clock, login, admin_a, director, branch_a, cash):
        c = login(admin_a)
        resp = c.post(
            "/xarajatlar/yangi/",
            {
                "branch": branch_a.pk,
                "category": rent().pk,
                "amount": "1 500 000",
                "spent_on": "16.11.2026",
                "method": cash.pk,
                "note": "Noyabr ijarasi",
            },
        )
        e = Expense.objects.get()
        assert resp.status_code == 302 and e.amount == 1_500_000 and e.method == cash
        text = page_text(c.get("/xarajatlar/"))
        assert "Ijara" in text and "1 500 000 so'm" in text
        assert "Xarajatlar" in page_text(c.get("/kassa/"))  # the Kassa subtotal
        d = login(director)
        d.post(f"/xarajatlar/{e.pk}/bekor-qilish/", {"reason": "xato"})
        assert Expense.objects.filter(kind="reversal").count() == 1


# --- staff salaries --------------------------------------------------------------------------


class TestStaffPay:
    def test_fixed_salary_on_the_sheet_and_frozen(self, clock, director, admin_a):
        set_settings({"salaries.start_month": 202611}, actor=director)
        salaries.set_staff_pay(
            actor=director, user=admin_a, amount=3_000_000, effective_from=D(2026, 11, 1)
        )
        salaries.add_adjustment(
            actor=director,
            teacher=admin_a,
            month=D(2026, 11, 1),
            kind="bonus",
            amount=200_000,
            reason="yaxshi ish",
        )
        sheet = salary_selectors.sheet(admin_a, admin_a.pk, D(2026, 11, 1))  # own sheet
        assert (sheet.totals.fixed, sheet.totals.total) == (3_000_000, 3_200_000)
        salaries.close_month(actor=director, month=D(2026, 11, 1))
        assert FixedLine.objects.get().amount == 3_000_000
        salaries.set_staff_pay(
            actor=director, user=admin_a, amount=3_500_000, effective_from=D(2026, 12, 1)
        )
        assert (
            salary_selectors.sheet(director, admin_a.pk, D(2026, 11, 1)).totals.fixed == 3_000_000
        )
        with pytest.raises(ValidationError):  # a closed month can't get a new amount
            salaries.set_staff_pay(
                actor=director, user=admin_a, amount=1, effective_from=D(2026, 11, 1)
            )
        payout = salaries.pay_out(
            actor=director, teacher=admin_a, month=D(2026, 11, 1), paid_on=TODAY
        )
        assert payout.amount == 3_200_000

    def test_only_salaried_people(self, director):
        with pytest.raises(ValidationError):
            salaries.set_staff_pay(
                actor=director, user=director, amount=1, effective_from=D(2026, 12, 1)
            )


# --- branch profit ---------------------------------------------------------------------------


class TestProfit:
    def test_numbers(self, clock, director, admin_a, branch_a, branch_b, group, cash):
        set_settings({"salaries.start_month": 202611}, actor=director)
        teacher = group.teacher
        s = make_student(admin_a, branch_a)
        st.enroll(actor=admin_a, student=s, group=group, start_date=D(2026, 11, 2))
        billing.payments.record_payment(
            actor=admin_a, student=s, amount=400_000, method=cash, paid_on=TODAY
        )
        manager_b = UserFactory(role=Role.SALES_MANAGER, branches=[branch_b])
        salaries.set_staff_pay(
            actor=director, user=manager_b, amount=2_000_000, effective_from=D(2026, 11, 1)
        )
        spend(admin_a, branch_a, 100_000, cash=cash)
        spend(director, None, 300_000)  # center-wide: all to branch A (only A collected)
        result = get_report("filial-foydasi").build(
            director, Params(D(2026, 11, 1), D(2026, 11, 30), None)
        )
        rows = {r[0]: r for r in result.rows}
        a, b = rows[branch_a.name], rows[branch_b.name]
        teacher_share = 200_000 if teacher else 0  # default rate 50%
        assert a[1:] == [
            400_000,
            0,
            0,
            teacher_share,
            0,
            100_000,
            300_000,
            400_000 - teacher_share - 400_000,
        ]
        assert b[1:] == [0, 0, 0, 0, 2_000_000, 0, 0, -2_000_000]
        assert result.totals[8] == a[8] + b[8]
        with pytest.raises(PermissionDenied):
            get_report("filial-foydasi").build(
                admin_a, Params(D(2026, 11, 1), D(2026, 11, 30), None)
            )
