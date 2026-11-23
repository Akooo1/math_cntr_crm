"""Daily cash report and close (docs/SPEC.md 6.4.9)."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit, dates
from apps.core.permissions import ensure_branch_access, require_perm

from ..models import CashDayClose, Payment, PaymentMethod


def day_report(branch_id: int, day: dt.date) -> dict:
    """Totals per method for the methods counted in the cash report, plus the transactions."""
    rows = list(
        Payment.objects.filter(branch_id=branch_id, paid_on=day, status=Payment.Status.CONFIRMED)
        .select_related("student", "method", "received_by", "reverses")
        .order_by("created_at", "id")
    )
    methods = {}
    for m in PaymentMethod.objects.filter(included_in_cash_close=True).order_by(
        "sort_order", "name"
    ):
        methods[m.pk] = {"method": m, "in": 0, "out": 0, "count": 0}
    for p in rows:
        bucket = methods.get(p.method_id)
        if bucket is None:
            continue
        bucket["count"] += 1
        if p.kind == Payment.Kind.PAYMENT:
            bucket["in"] += p.amount
        else:
            bucket["out"] += p.amount
    lines = [
        dict(b, net=b["in"] - b["out"])
        for b in methods.values()
        if b["count"] or b["method"].is_active
    ]
    return {
        "rows": [p for p in rows if p.method_id in methods],
        "methods": lines,
        "total_in": sum(b["in"] for b in lines),
        "total_out": sum(b["out"] for b in lines),
        "total_net": sum(b["net"] for b in lines),
        "count": sum(b["count"] for b in lines),
    }


def snapshot(report: dict) -> dict:
    return {
        "methods": [
            {
                "method_id": b["method"].pk,
                "name": b["method"].name,
                "in": b["in"],
                "out": b["out"],
                "net": b["net"],
                "count": b["count"],
            }
            for b in report["methods"]
        ],
        "total_in": report["total_in"],
        "total_out": report["total_out"],
        "total_net": report["total_net"],
        "count": report["count"],
    }


def close_day(*, actor, branch, day: dt.date, note: str = "") -> CashDayClose:
    """Lock the branch-day: no payment, reversal or refund dated that day afterwards."""
    require_perm(actor, "billing.cash.close")
    ensure_branch_access(actor, branch.pk)
    if day > dates.today():
        raise ValidationError(_("A future day can't be closed."))
    with transaction.atomic():
        if CashDayClose.objects.select_for_update().filter(branch=branch, date=day).exists():
            raise ValidationError(_("This day is already closed."))
        totals = snapshot(day_report(branch.pk, day))
        close = CashDayClose.objects.create(
            branch=branch, date=day, closed_by=actor, totals=totals, note=note
        )
        audit.record(
            actor, "billing.cash_day.close", close, after={"date": day.isoformat(), **totals}
        )
    return close
