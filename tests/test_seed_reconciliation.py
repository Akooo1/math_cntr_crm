"""Acceptance: the debtors list, the cash report and the reports match the seeded money
(brief, 'Done when').

The numbers are recomputed here from the raw rows (charges, discount lines, adjustments,
payments) with plain Python, independently of the views and the allocation cache.
"""

import datetime as dt
from collections import defaultdict

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.billing import selectors, services
from apps.billing.models import (
    CashDayClose,
    Charge,
    ChargeAdjustment,
    ChargeDiscount,
    Payment,
    StudentBalance,
)
from apps.core import dates


def raw_net() -> dict[int, int]:
    net = {c.pk: c.amount for c in Charge.objects.all()}
    for d in ChargeDiscount.objects.all():
        net[d.charge_id] -= d.amount
    for a in ChargeAdjustment.objects.all():
        net[a.charge_id] += a.amount
    return net


def raw_overdue_by_student() -> dict[int, int]:
    """FIFO from scratch: money in (minus reversals and refunds) pays charges by due date."""
    net = raw_net()
    cutoff = selectors.overdue_cutoff()
    charges = defaultdict(list)
    for c in Charge.objects.order_by("due_date", "created_at", "id"):
        charges[c.student_id].append(c)
    money = defaultdict(int)
    for p in Payment.objects.filter(status="confirmed"):
        money[p.student_id] += p.amount if p.kind == "payment" else -p.amount
    out = {}
    for sid, items in charges.items():
        left = money[sid]
        overdue = 0
        for c in items:
            covered = min(max(left, 0), max(net[c.pk], 0))
            left -= covered
            if c.due_date < cutoff:
                overdue += max(net[c.pk], 0) - covered
        if overdue:
            out[sid] = overdue
    return out


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_seeded_money_reconciles():
    """One seed (about 10 s), four independent checks."""
    call_command("seed_demo")
    check_debtors()
    check_balances()
    check_cash()
    check_reports()


def check_debtors():
    director = get_user_model().objects.get(phone="+998900000001")
    listed = {r["student"].pk: r["overdue"] for r in selectors.debtors(director)}
    assert listed, "the demo data should contain debtors"
    assert listed == raw_overdue_by_student()


def check_balances():
    net = raw_net()
    charged = defaultdict(int)
    for c in Charge.objects.all():
        charged[c.student_id] += net[c.pk]
    paid = defaultdict(int)
    for p in Payment.objects.filter(status="confirmed"):
        paid[p.student_id] += p.amount if p.kind == "payment" else -p.amount
    for row in StudentBalance.objects.all():
        assert row.balance == paid[row.student_id] - charged[row.student_id]


def check_cash():
    by_day = defaultdict(int)
    for p in Payment.objects.filter(method__included_in_cash_close=True):
        by_day[(p.branch_id, p.paid_on)] += p.amount if p.kind == "payment" else -p.amount
    assert by_day
    for (branch_id, day), total in by_day.items():
        report = services.cash.day_report(branch_id, day)
        assert report["total_net"] == total
        close = CashDayClose.objects.filter(branch_id=branch_id, date=day).first()
        if close:
            assert close.totals["total_net"] == total  # nothing changed after closing
    assert CashDayClose.objects.exists()
    assert not CashDayClose.objects.filter(date__gte=dates.today() - dt.timedelta(days=2)).exists()


def check_reports():
    from apps.core.reports import Params, get_report

    director = get_user_model().objects.get(phone="+998900000001")
    net = raw_net()
    start = Charge.objects.order_by("due_date").first().due_date.replace(day=1)
    end = dates.today()
    params = Params(start, end, None)
    charged_by_month, collected_by_month = defaultdict(int), defaultdict(int)
    for c in Charge.objects.filter(due_date__gte=start, due_date__lte=end):
        charged_by_month[c.due_date.replace(day=1)] += net[c.pk]
    for p in Payment.objects.filter(status="confirmed", paid_on__gte=start, paid_on__lte=end):
        collected_by_month[p.paid_on.replace(day=1)] += (
            p.amount if p.kind == "payment" else -p.amount
        )
    monthly = get_report("oylar").build(director, params)
    assert {r[0]: r[1] for r in monthly.rows if r[1]} == dict(charged_by_month)
    assert {r[0]: r[2] for r in monthly.rows if r[2]} == {
        m: v for m, v in collected_by_month.items() if v
    }
    # Branch and method reports add up to the same totals.
    branches = get_report("filiallar").build(director, params)
    methods = get_report("tolov-usullari").build(director, params)
    assert branches.totals[1:3] == monthly.totals[1:3]
    assert methods.totals[3] == monthly.totals[2]
    # Overdue debt in the reports is the debtors list total.
    debt = get_report("qarzdorlik").build(director, params)
    assert debt.totals[2] == sum(raw_overdue_by_student().values()) == branches.totals[4]
