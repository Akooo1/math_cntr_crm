"""Salary writes (docs/SPEC.md §13). Direktor only. Every write is audited."""

import datetime as dt
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils.translation import gettext as _

from apps.core import audit, dates
from apps.core.datemath import add_months, month_start
from apps.core.permissions import require_perm
from apps.core.roles import Role

from .. import selectors
from ..domain import calc
from ..models import Adjustment, Line, Month, Payout, Rate

LOCK_KEY = 7_410_001  # pg advisory lock: one salary write at a time


def _lock():
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_KEY])


def _teacher(user):
    if user.role != Role.TEACHER:
        raise ValidationError(_("Only teachers have a salary rate."))


def add_rate(*, actor, teacher, rate_bp: int, effective_from: dt.date, reason: str = "") -> Rate:
    require_perm(actor, "salaries.manage")
    _teacher(teacher)
    if not 0 <= rate_bp <= 10_000:
        raise ValidationError(_("A percent must be between 0 and 100."))
    effective_from = month_start(effective_from)
    closed = selectors.closed_months()
    if effective_from in closed or any(m > effective_from for m in closed):
        raise ValidationError(_("That month is already closed. Choose a later month."))
    with transaction.atomic():
        _lock()
        rate = Rate.objects.create(
            teacher=teacher,
            rate_bp=rate_bp,
            effective_from=effective_from,
            reason=reason,
            created_by=actor,
        )
        audit.record(actor, "salaries.rate.create", rate, after=audit.snapshot(rate), reason=reason)
    return rate


def close_month(*, actor, month: dt.date) -> Month:
    """Freeze the open month's lines. Months close in order and not before they start.
    A negative total is carried into the next month as a deduction."""
    require_perm(actor, "salaries.manage")
    with transaction.atomic():
        _lock()
        if month != selectors.open_month():
            raise ValidationError(_("Close the earlier months first."))
        if month > month_start(dates.today()):
            raise ValidationError(_("This month hasn't started yet."))
        lines = selectors.draft(month)
        by_teacher = defaultdict(list)
        for d in lines:
            by_teacher[d.teacher_id].append(d)
        adjustments = defaultdict(list)
        for a in Adjustment.objects.filter(month=month):
            adjustments[a.teacher_id].append((a.kind, a.amount))
        totals = {
            str(tid): calc.totals(by_teacher.get(tid, []), adjustments.get(tid, [])).total
            for tid in set(by_teacher) | set(adjustments)
        }
        closed = Month.objects.create(month=month, closed_by=actor, totals=totals)
        Line.objects.bulk_create(
            Line(
                month=closed,
                teacher_id=d.teacher_id,
                student_id=d.student_id,
                group_id=d.group_id,
                payment_month=d.payment_month,
                kind=d.kind,
                base=d.base,
                rate_bp=d.rate_bp,
                amount=d.amount,
            )
            for d in lines
        )
        nxt = add_months(month, 1)
        for teacher_id, total in totals.items():
            if total < 0:
                Adjustment.objects.create(
                    month=nxt,
                    teacher_id=int(teacher_id),
                    kind=Adjustment.Kind.CARRY,
                    amount=total,
                    reason=_("Carried over from %(month)s") % {"month": f"{month:%m.%Y}"},
                )
        audit.record(
            actor,
            "salaries.month.close",
            closed,
            after={"month": month.isoformat(), "line_count": len(lines), "teachers": totals},
        )
    return closed


def add_adjustment(
    *, actor, teacher, month: dt.date, kind: str, amount: int, reason: str
) -> Adjustment:
    """Bonus (+) or deduction (-) for a month that is not closed yet."""
    require_perm(actor, "salaries.manage")
    _teacher(teacher)
    if kind not in (Adjustment.Kind.BONUS, Adjustment.Kind.DEDUCTION):
        raise ValidationError(_("Choose a bonus or a deduction."))
    if amount <= 0:
        raise ValidationError(_("The amount must be positive."))
    if not reason.strip():
        raise ValidationError(_("Write the reason."))
    month = month_start(month)
    with transaction.atomic():
        _lock()
        if month < selectors.start_month() or month in selectors.closed_months():
            raise ValidationError(_("This month is closed."))
        adj = Adjustment.objects.create(
            month=month,
            teacher=teacher,
            kind=kind,
            amount=amount if kind == Adjustment.Kind.BONUS else -amount,
            reason=reason.strip(),
            created_by=actor,
        )
        audit.record(
            actor, "salaries.adjustment.create", adj, after=audit.snapshot(adj), reason=reason
        )
    return adj


def delete_adjustment(*, actor, adjustment: Adjustment) -> None:
    require_perm(actor, "salaries.manage")
    with transaction.atomic():
        _lock()
        if adjustment.kind == Adjustment.Kind.CARRY:
            raise ValidationError(_("A carry-over can't be deleted."))
        if adjustment.month in selectors.closed_months():
            raise ValidationError(_("This month is closed."))
        before = audit.snapshot(adjustment)
        audit.record(actor, "salaries.adjustment.delete", adjustment, before=before)
        adjustment.delete()


def pay_out(*, actor, teacher, month: dt.date, paid_on: dt.date, note: str = "") -> Payout:
    """Record that the teacher got the closed month's total in cash."""
    require_perm(actor, "salaries.manage")
    if paid_on > dates.today():
        raise ValidationError(_("The date can't be in the future."))
    with transaction.atomic():
        _lock()
        closed = Month.objects.filter(month=month).first()
        if closed is None:
            raise ValidationError(_("Close the month first."))
        sheet = selectors.sheets_for(month, {teacher.pk})[0]
        if sheet.payout is not None:
            raise ValidationError(_("This salary is already paid out."))
        if sheet.totals.total <= 0:
            raise ValidationError(_("There is nothing to pay for this month."))
        payout = Payout.objects.create(
            month=closed,
            teacher=teacher,
            amount=sheet.totals.total,
            paid_on=paid_on,
            note=note,
            created_by=actor,
        )
        audit.record(actor, "salaries.payout.create", payout, after=audit.snapshot(payout))
    return payout


def cancel_payout(*, actor, payout: Payout, reason: str) -> Payout:
    require_perm(actor, "salaries.manage")
    if not reason.strip():
        raise ValidationError(_("Write the reason."))
    with transaction.atomic():
        _lock()
        if payout.kind != Payout.Kind.PAYOUT or Payout.objects.filter(cancels=payout).exists():
            raise ValidationError(_("This payout is already cancelled."))
        cancel = Payout.objects.create(
            month=payout.month,
            teacher=payout.teacher,
            kind=Payout.Kind.CANCEL,
            amount=payout.amount,
            paid_on=dates.today(),
            note=reason.strip(),
            cancels=payout,
            created_by=actor,
        )
        audit.record(
            actor,
            "salaries.payout.cancel",
            payout,
            after=audit.snapshot(cancel),
            reason=reason,
        )
    return cancel
