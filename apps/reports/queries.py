"""Read-only aggregations (docs/SPEC.md 7.1 item 7). All money is whole so'm (int)."""

import datetime as dt
from collections import defaultdict

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth

from apps.billing.models import Allocation, ChargeNet, Payment
from apps.billing.selectors import overdue_cutoff
from apps.core.datemath import add_months, month_start
from apps.core.permissions import apply_branch_filter, scope_by_branch
from apps.crm.models import Lead


def _int(v) -> int:
    return int(v or 0)


def charges(user, branch_id, start=None, end=None):
    qs = apply_branch_filter(scope_by_branch(ChargeNet.objects.all(), user), branch_id)
    if start:
        qs = qs.filter(due_date__gte=start)
    if end:
        qs = qs.filter(due_date__lte=end)
    return qs


def payments(user, branch_id, start=None, end=None):
    qs = Payment.objects.filter(status="confirmed")
    qs = apply_branch_filter(scope_by_branch(qs, user), branch_id)
    if start:
        qs = qs.filter(paid_on__gte=start)
    if end:
        qs = qs.filter(paid_on__lte=end)
    return qs


SIGNED = Sum("amount", filter=Q(kind="payment"))
OUT = Sum("amount", filter=~Q(kind="payment"))


def collected_total(qs) -> int:
    r = qs.aggregate(i=SIGNED, o=OUT)
    return _int(r["i"]) - _int(r["o"])


def months(start: dt.date, end: dt.date) -> list[dt.date]:
    out, m = [], month_start(start)
    while m <= month_start(end):
        out.append(m)
        m = add_months(m, 1)
    return out


def by_month(user, branch_id, start, end) -> list[dict]:
    charged = defaultdict(int)
    for r in (
        charges(user, branch_id, start, end)
        .annotate(m=TruncMonth("due_date"))
        .values("m")
        .annotate(t=Sum("net"))
    ):
        charged[r["m"]] += _int(r["t"])
    collected = defaultdict(int)
    for r in (
        payments(user, branch_id, start, end)
        .annotate(m=TruncMonth("paid_on"))
        .values("m")
        .annotate(i=SIGNED, o=OUT)
    ):
        collected[r["m"]] += _int(r["i"]) - _int(r["o"])
    return [
        {"month": m, "charged": charged[m], "collected": collected[m]} for m in months(start, end)
    ]


def debt(user, branch_id, **filters):
    """(open total, overdue) right now."""
    qs = apply_branch_filter(
        scope_by_branch(ChargeNet.objects.filter(net__gt=F("paid")), user), branch_id
    )
    qs = qs.filter(**filters)
    open_ = _int(qs.aggregate(t=Sum(F("net") - F("paid")))["t"])
    overdue = _int(
        qs.filter(due_date__lt=overdue_cutoff()).aggregate(t=Sum(F("net") - F("paid")))["t"]
    )
    return open_, overdue


def by_branch(user, branch_id, start, end) -> list[dict]:
    from apps.settings.models import Branch

    branches = Branch.objects.order_by("name")
    rows = []
    for b in branches:
        if branch_id and b.pk != branch_id:
            continue
        from apps.core.permissions import can_access_branch

        if not can_access_branch(user, b.pk):
            continue
        open_, overdue = debt(user, b.pk)
        rows.append(
            {
                "branch": b,
                "charged": _int(charges(user, b.pk, start, end).aggregate(t=Sum("net"))["t"]),
                "collected": collected_total(payments(user, b.pk, start, end)),
                "open": open_,
                "overdue": overdue,
            }
        )
    return rows


def by_course(user, branch_id, start, end) -> list[dict]:
    """Charged by the charge's course; collected = money from payments made in the period
    that went to the course's charges (FIFO allocation)."""
    from apps.settings.models import Course

    names = dict(Course.objects.values_list("id", "name"))
    charged = defaultdict(int)
    for r in charges(user, branch_id, start, end).values("course_id").annotate(t=Sum("net")):
        charged[r["course_id"]] += _int(r["t"])
    pays = payments(user, branch_id, start, end).filter(kind="payment")
    collected = defaultdict(int)
    for r in (
        Allocation.objects.filter(payment__in=pays)
        .values("charge__course_id")
        .annotate(t=Sum("amount"))
    ):
        collected[r["charge__course_id"]] += _int(r["t"])
    keys = sorted(set(charged) | set(collected), key=lambda k: (k is None, names.get(k, "")))
    return [
        {"course": names.get(k), "charged": charged[k], "collected": collected[k]} for k in keys
    ]


def by_method(user, branch_id, start, end) -> list[dict]:
    rows = (
        payments(user, branch_id, start, end)
        .values("method__name", "method__sort_order")
        .annotate(i=SIGNED, o=OUT, n=Count("id"))
        .order_by("method__sort_order", "method__name")
    )
    return [
        {
            "method": r["method__name"],
            "in": _int(r["i"]),
            "out": _int(r["o"]),
            "net": _int(r["i"]) - _int(r["o"]),
            "count": r["n"],
        }
        for r in rows
    ]


def debt_by_course(user, branch_id) -> list[dict]:
    from apps.settings.models import Course

    names = dict(Course.objects.values_list("id", "name"))
    cutoff = overdue_cutoff()
    qs = apply_branch_filter(
        scope_by_branch(ChargeNet.objects.filter(net__gt=F("paid")), user), branch_id
    )
    rows = qs.values("course_id").annotate(
        open=Sum(F("net") - F("paid")),
        overdue=Sum(F("net") - F("paid"), filter=Q(due_date__lt=cutoff)),
        debtors=Count("student_id", filter=Q(due_date__lt=cutoff), distinct=True),
    )
    out = [
        {
            "course": names.get(r["course_id"]),
            "open": _int(r["open"]),
            "overdue": _int(r["overdue"]),
            "debtors": r["debtors"],
        }
        for r in rows
    ]
    return sorted(out, key=lambda r: -r["overdue"])


def leads_by(user, branch_id, start, end, field: str) -> list[dict]:
    """Leads created in the period, grouped by `field`; converted = became a student."""
    qs = apply_branch_filter(scope_by_branch(Lead.objects.all(), user), branch_id)
    qs = qs.filter(created_at__date__gte=start, created_at__date__lte=end)
    rows = qs.values(field).annotate(
        total=Count("id"),
        converted=Count("id", filter=Q(student__isnull=False)),
        lost=Count("id", filter=Q(stage__kind="lost")),
    )
    return list(rows)
