"""Expense reads, the Kassa lines and the branch profit report (docs/SPEC.md §20)."""

import datetime as dt
from collections import defaultdict

from django.db.models import Q, Sum
from django.http import Http404
from django.utils.translation import gettext as _

from apps.billing.services import round_amount
from apps.core.permissions import apply_branch_filter, require_perm, scope_by_branch

from . import domain
from .models import Expense


def expenses_for(user, branch_filter=None):
    """Branch staff see their branches' expenses; center-wide ones only the Direktor."""
    require_perm(user, "expenses.view")
    qs = scope_by_branch(Expense.objects.all(), user)
    return apply_branch_filter(qs, branch_filter).select_related(
        "branch", "category", "method", "created_by", "reverses"
    )


def net_total(qs) -> int:
    r = qs.aggregate(
        e=Sum("amount", filter=Q(kind=Expense.Kind.EXPENSE)),
        r=Sum("amount", filter=Q(kind=Expense.Kind.REVERSAL)),
    )
    return int(r["e"] or 0) - int(r["r"] or 0)


def get_expense(user, pk) -> Expense:
    expense = expenses_for(user).filter(pk=pk).first()
    if expense is None:
        raise Http404
    return expense


# --- Kassa (billing's cash-source hook) ---------------------------------------------------


def cash_lines(branch_id: int, day: dt.date) -> list:
    from django.urls import reverse

    from apps.billing.services.cash import CashLine

    out = []
    for e in Expense.objects.filter(
        branch_id=branch_id, spent_on=day, method__isnull=False
    ).select_related("category", "created_by"):
        cancel = e.kind == Expense.Kind.REVERSAL
        out.append(
            CashLine(
                source="expenses",
                method_id=e.method_id,
                direction="in" if cancel else "out",
                amount=e.amount,
                at=e.created_at,
                by_name=e.created_by.full_name,
                description=f"{e.category.name}{': ' + e.note if e.note else ''}",
                kind_label=_("Cancelled") if cancel else "",
                url=reverse("expenses:detail", args=[e.reverses_id if cancel else e.pk]),
            )
        )
    return out


def cash_active_days(since: dt.date, until: dt.date) -> set:
    return set(
        Expense.objects.filter(
            method__isnull=False, spent_on__gte=since, spent_on__lte=until
        ).values_list("branch_id", "spent_on")
    )


# --- Branch profit --------------------------------------------------------------------------


def _salary_costs(months: list[dt.date]):
    """Teacher and staff salaries of the months, by branch where known.

    Returns ({branch_id: teacher pay}, {branch_id: staff pay}, shared) where shared is pay
    that belongs to no single branch (teachers' bonuses and deductions, staff working in
    several branches). Months not yet calculated (after the open month) count nothing."""
    from django.contrib.auth import get_user_model

    from apps.salaries import selectors as salaries
    from apps.salaries.models import Adjustment, FixedLine, Line
    from apps.students.models import Group

    teacher_pay, staff_pay = defaultdict(int), defaultdict(int)
    shared = 0
    group_branch = dict(Group.objects.values_list("id", "branch_id"))
    from apps.settings.models import UserBranch

    User = get_user_model()
    links = defaultdict(list)
    for uid, bid in UserBranch.objects.values_list("user_id", "branch_id"):
        links[uid].append(bid)
    single_branch = {uid: bids[0] for uid, bids in links.items() if len(bids) == 1}
    roles = dict(User.objects.values_list("id", "role"))
    for month in months:
        state = salaries.month_state(month)
        if state == salaries.CLOSED:
            lines = Line.objects.filter(month__month=month).values_list("group_id", "amount")
            fixed = dict(
                FixedLine.objects.filter(month__month=month).values_list("user_id", "amount")
            )
        elif state == salaries.OPEN:
            lines = [(d.group_id, d.amount) for d in salaries.draft(month)]
            fixed = salaries.fixed_amounts(month)
        else:
            continue
        for group_id, amount in lines:
            teacher_pay[group_branch[group_id]] += amount
        for uid, amount in fixed.items():
            branch = single_branch.get(uid)
            if branch is None:
                shared += amount
            else:
                staff_pay[branch] += amount
        for uid, amount in (
            Adjustment.objects.filter(month=month)
            .exclude(kind=Adjustment.Kind.CARRY)
            .values_list("teacher_id", "amount")
        ):
            branch = single_branch.get(uid)
            if roles.get(uid) != "teacher" and branch is not None:
                staff_pay[branch] += amount
            else:
                shared += amount
    return teacher_pay, staff_pay, shared


def _store(user, branch_ids, p):
    """{branch_id: (desk sales paid at once, purchase cost of what was sold)}."""
    from apps.core.reports import Params
    from apps.store import selectors as store

    out = {}
    for bid in branch_ids:
        r = store.stock_report(user, Params(p.date_from, p.date_to, bid))
        sales = sum((row[5] or 0) - (row[6] or 0) for row in r.rows)
        cost = sum(row[7] or 0 for row in r.rows)
        out[bid] = (sales, cost)
    return out


def _collected(branch_ids, start, end) -> dict[int, int]:
    """Students' payments per branch, net of reversals and refunds (Tushum)."""
    from apps.billing.models import Payment

    out = dict.fromkeys(branch_ids, 0)
    for r in (
        Payment.objects.filter(status="confirmed", paid_on__gte=start, paid_on__lte=end)
        .values("branch_id")
        .annotate(
            i=Sum("amount", filter=Q(kind="payment")), o=Sum("amount", filter=~Q(kind="payment"))
        )
    ):
        out[r["branch_id"]] = int(r["i"] or 0) - int(r["o"] or 0)
    return out


def profit_report(user, p):
    """Per branch for the period: students' payments + desk sales, minus purchase cost,
    teacher salaries, staff salaries, the branch's expenses and its share of the
    center-wide costs (split by students' payments). Salaries count for the months that
    start inside the period."""
    from apps.core.datemath import add_months, month_start
    from apps.core.reports import Col, Result
    from apps.settings.models import Branch

    require_perm(user, "expenses.profit")
    branches = list(Branch.objects.order_by("name"))
    ids = [b.pk for b in branches]
    collected = _collected(ids, p.date_from, p.date_to)
    store = _store(user, ids, p)
    months, m = [], month_start(p.date_from)
    if m < p.date_from:
        m = add_months(m, 1)
    while m <= p.date_to:
        months.append(m)
        m = add_months(m, 1)
    teacher_pay, staff_pay, shared_pay = _salary_costs(months)
    in_period = Expense.objects.filter(spent_on__gte=p.date_from, spent_on__lte=p.date_to)
    own = defaultdict(int)
    for row in (
        in_period.filter(branch__isnull=False)
        .values("branch_id")
        .annotate(
            e=Sum("amount", filter=Q(kind="expense")), r=Sum("amount", filter=Q(kind="reversal"))
        )
    ):
        own[row["branch_id"]] = int(row["e"] or 0) - int(row["r"] or 0)
    shared_expenses = net_total(in_period.filter(branch__isnull=True))
    share = domain.split(shared_expenses + shared_pay, collected, round_amount)

    rows = []
    for b in branches:
        if p.branch_id and b.pk != p.branch_id:
            continue
        sales, cost = store.get(b.pk, (0, 0))
        income = collected[b.pk] + sales
        costs = cost + teacher_pay[b.pk] + staff_pay[b.pk] + own[b.pk] + share.get(b.pk, 0)
        rows.append(
            [
                b.name,
                collected[b.pk],
                sales,
                cost,
                teacher_pay[b.pk],
                staff_pay[b.pk],
                own[b.pk],
                share.get(b.pk, 0),
                income - costs,
            ]
        )
    totals = [_("Total")] + [sum(r[i] for r in rows) for i in range(1, 9)]
    return Result(
        columns=[
            Col(_("Branch")),
            Col(_("Students' payments"), "money"),
            Col(_("Desk sales"), "money"),
            Col(_("Purchase cost"), "money"),
            Col(_("Teachers' salaries"), "money"),
            Col(_("Staff salaries"), "money"),
            Col(_("Expenses"), "money"),
            Col(_("Share of center-wide costs"), "money"),
            Col(_("Profit"), "money"),
        ],
        rows=rows,
        totals=totals,
        note=_(
            "Money that came in during the period minus what it cost. Books given 'pay later' "
            "count when the parent pays. Salaries count for the months that start in the "
            "period (an open month as calculated so far). Center-wide expenses, teachers' "
            "bonuses and deductions and staff working in several branches are split between "
            "branches by students' payments."
        ),
    )
