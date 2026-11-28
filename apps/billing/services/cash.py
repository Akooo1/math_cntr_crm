"""Daily cash report and close (docs/SPEC.md 6.4.9)."""

import dataclasses
import datetime as dt
from collections.abc import Callable

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core import audit, dates
from apps.core.permissions import ensure_branch_access, require_perm

from ..models import CashDayClose, CashDayReopen, Payment, PaymentMethod

# --- Extension point: other modules' money in the cash report (SPEC 17.4) ----------------


@dataclasses.dataclass(frozen=True)
class CashLine:
    """One movement of cash that is not a student payment (e.g. a counter sale)."""

    source: str  # CashSource.code
    method_id: int  # billing_payment_method row
    direction: str  # "in" | "out"
    amount: int  # > 0, whole so'm
    at: dt.datetime
    by_name: str
    description: str  # already translated
    kind_label: str = ""  # e.g. "Bekor qilish"; empty for a plain sale
    url: str = ""

    @property
    def signed_amount(self) -> int:
        return self.amount if self.direction == "in" else -self.amount


@dataclasses.dataclass(frozen=True)
class CashSource:
    code: str
    label: object  # lazy Uzbek label, shown as a Kassa subtotal
    lines: Callable[[int, dt.date], list[CashLine]]  # (branch_id, day) -> lines
    # (since, until) -> {(branch_id, day)} with lines, so unclosed days are flagged too
    active_days: Callable[[dt.date, dt.date], set] | None = None
    order: int = 100


PAYMENTS_SOURCE = "payments"
_sources: dict[str, CashSource] = {}


def register_cash_source(source: CashSource) -> None:
    if source.code == PAYMENTS_SOURCE:
        raise ValueError("reserved cash source code")
    _sources[source.code] = source


def cash_sources() -> list[CashSource]:
    return sorted(_sources.values(), key=lambda s: (s.order, s.code))


LOCK_NAMESPACE = 7_420_000  # pg advisory lock class for cash days (salaries use 7_410_001)


def lock_day(branch_id: int, day: dt.date) -> None:
    """Serialise every cash write and the close of one branch-day (call inside a transaction).

    The closed-day triggers only see committed closes; without this lock a payment committed
    while the day is being closed could land on the closed day outside its snapshot."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            [LOCK_NAMESPACE + branch_id % 10_000, day.toordinal()],
        )


def day_report(branch_id: int, day: dt.date) -> dict:
    """Totals per method for the methods counted in the cash report, plus the transactions:
    student payments (`rows`) and the lines of registered cash sources (`extra_lines`)."""
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
    sources = {PAYMENTS_SOURCE: _bucket(PAYMENTS_SOURCE, gettext_lazy("Students' payments"))}
    for p in rows:
        bucket = methods.get(p.method_id)
        if bucket is None:
            continue
        direction = "in" if p.kind == Payment.Kind.PAYMENT else "out"
        for b in (bucket, sources[PAYMENTS_SOURCE]):
            b["count"] += 1
            b[direction] += p.amount
    extra = []
    for source in cash_sources():
        sources[source.code] = _bucket(source.code, source.label)
        for line in source.lines(branch_id, day):
            bucket = methods.get(line.method_id)
            if bucket is None:
                continue
            extra.append(line)
            for b in (bucket, sources[source.code]):
                b["count"] += 1
                b[line.direction] += line.amount
    extra.sort(key=lambda line: line.at)
    lines = [
        dict(b, net=b["in"] - b["out"])
        for b in methods.values()
        if b["count"] or b["method"].is_active
    ]
    return {
        "rows": [p for p in rows if p.method_id in methods],
        "extra_lines": extra,
        "sources": [dict(b, net=b["in"] - b["out"]) for b in sources.values()],
        "has_sources": bool(_sources),
        "methods": lines,
        "total_in": sum(b["in"] for b in lines),
        "total_out": sum(b["out"] for b in lines),
        "total_net": sum(b["net"] for b in lines),
        "count": sum(b["count"] for b in lines),
    }


def _bucket(code: str, label) -> dict:
    return {"code": code, "label": label, "in": 0, "out": 0, "count": 0}


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
        "sources": [
            {k: b[k] for k in ("code", "in", "out", "net", "count")} for b in report["sources"]
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
        lock_day(branch.pk, day)
        if CashDayClose.objects.in_force().filter(branch=branch, date=day).exists():
            raise ValidationError(_("This day is already closed."))
        totals = snapshot(day_report(branch.pk, day))
        close = CashDayClose.objects.create(
            branch=branch, date=day, closed_by=actor, totals=totals, note=note
        )
        audit.record(
            actor, "billing.cash_day.close", close, after={"date": day.isoformat(), **totals}
        )
    return close


def reopen_day(*, actor, branch, day: dt.date, reason: str) -> CashDayReopen:
    """Undo a close (Direktor, with a reason; SPEC §24). Payments, reversals and refunds can
    be dated that day again; closing it again stores a new snapshot. The close row stays."""
    require_perm(actor, "billing.cash.reopen")
    ensure_branch_access(actor, branch.pk)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError(_("Write why the day is reopened."))
    with transaction.atomic():
        lock_day(branch.pk, day)
        close = CashDayClose.objects.in_force().filter(branch=branch, date=day).first()
        if close is None:
            raise ValidationError(_("This day is not closed."))
        reopen = CashDayReopen.objects.create(close=close, reopened_by=actor, reason=reason)
        audit.record(
            actor,
            "billing.cash_day.reopen",
            close,
            before={"date": day.isoformat(), **close.totals},
            branch_id=branch.pk,
            reason=reason,
        )
    return reopen
