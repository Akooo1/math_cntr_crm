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
from ..models import Adjustment, Advance, FixedLine, Line, Month, Payout, Rate, StaffPay

LOCK_KEY = 7_410_001  # pg advisory lock: one salary write at a time


def _lock():
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_KEY])


def _teacher(user):
    if user.role != Role.TEACHER:
        raise ValidationError(_("Only teachers have a salary rate."))


def _salaried(user):
    if user.role not in selectors.SALARIED_ROLES:
        raise ValidationError(_("Only teachers and staff have a salary."))


def set_staff_pay(
    *, actor, user, amount: int, effective_from: dt.date, reason: str = ""
) -> StaffPay:
    """A fixed monthly salary from a month on (0 stops it). Closed months never change."""
    require_perm(actor, "salaries.manage")
    _salaried(user)
    if amount < 0:
        raise ValidationError(_("The amount can't be negative."))
    effective_from = month_start(effective_from)
    closed = selectors.closed_months()
    if effective_from in closed or any(m > effective_from for m in closed):
        raise ValidationError(_("That month is already closed. Choose a later month."))
    with transaction.atomic():
        _lock()
        row = StaffPay.objects.create(
            user=user,
            amount=amount,
            effective_from=effective_from,
            reason=reason,
            created_by=actor,
        )
        audit.record(
            actor, "salaries.staff_pay.create", row, after=audit.snapshot(row), reason=reason
        )
    return row


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
        fixed = selectors.fixed_amounts(month)
        given = {
            tid: sum(a.amount for a in rows)
            for tid, rows in selectors.active_advances(month).items()
        }
        totals = {
            str(tid): calc.totals(
                by_teacher.get(tid, []), adjustments.get(tid, []), fixed.get(tid, 0)
            ).total
            for tid in set(by_teacher) | set(adjustments) | set(fixed) | set(given)
        }
        closed = Month.objects.create(month=month, closed_by=actor, totals=totals)
        FixedLine.objects.bulk_create(
            FixedLine(month=closed, user_id=uid, amount=amount) for uid, amount in fixed.items()
        )
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
            total -= given.get(int(teacher_id), 0)  # advances already handed over
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
    _salaried(teacher)
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


def _kassa(branch, method, day: dt.date) -> None:
    """Money out of (or back into) a branch's Kassa: a cash desk method, an open day,
    within the backdating window. Call inside the transaction (SPEC §24)."""
    from apps.billing import selectors as billing_selectors
    from apps.billing.services.cash import lock_day
    from apps.core.system_settings import get_setting

    if branch is None or method is None:
        raise ValidationError(_("Choose the branch and the Kassa method."))
    if not method.included_in_cash_close or not method.is_active:
        raise ValidationError(_("Choose a cash desk method."))
    today = dates.today()
    if day > today:
        raise ValidationError(_("The date can't be in the future."))
    window = get_setting("billing.backdate_days")
    if (today - day).days > window:
        raise ValidationError(
            _("A cash desk payment can be dated at most %(n)s days back.") % {"n": window}
        )
    lock_day(branch.pk, day)
    if billing_selectors.is_day_closed(branch.pk, day):
        raise ValidationError(_("This day is closed in the Kassa. Choose another date."))


def give_advance(
    *, actor, person, amount: int, given_on: dt.date, branch, method, note: str = ""
) -> Advance:
    """Maosh avansi from a branch's Kassa (Direktor only). It is taken from the earliest
    salary month not closed yet and may not be more than that month has earned so far
    minus advances already given (owner's rules, SPEC §24)."""
    require_perm(actor, "salaries.manage")
    _salaried(person)
    if amount <= 0:
        raise ValidationError(_("Enter an amount greater than zero."))
    with transaction.atomic():
        _lock()
        _kassa(branch, method, given_on)
        month = selectors.open_month()
        sheet = selectors.sheets_for(month, {person.pk})[0]
        room = sheet.totals.to_pay
        if amount > room:
            raise ValidationError(
                _("At most %(amount)s can be given now: what %(month)s has earned so far.")
                % {"amount": _money(max(room, 0)), "month": f"{month:%m.%Y}"}
            )
        advance = Advance.objects.create(
            person=person,
            month=month,
            amount=amount,
            given_on=given_on,
            branch=branch,
            method=method,
            note=note.strip(),
            created_by=actor,
        )
        audit.record(
            actor,
            "salaries.advance.create",
            advance,
            after=audit.snapshot(advance),
            branch_id=branch.pk,
        )
    return advance


def cancel_advance(*, actor, advance: Advance, reason: str) -> Advance:
    """Undo an advance: the money goes back into today's Kassa of the same branch."""
    require_perm(actor, "salaries.manage")
    if not reason.strip():
        raise ValidationError(_("Write the reason."))
    with transaction.atomic():
        _lock()
        advance = Advance.objects.get(pk=advance.pk)
        if advance.kind != Advance.Kind.ADVANCE or Advance.objects.filter(cancels=advance).exists():
            raise ValidationError(_("This advance is already cancelled."))
        if Month.objects.filter(month=advance.month).exists():
            raise ValidationError(_("The month is closed: this advance is part of it."))
        today = dates.today()
        _kassa(advance.branch, advance.method, today)
        cancel = Advance.objects.create(
            person=advance.person,
            month=advance.month,
            kind=Advance.Kind.CANCEL,
            amount=advance.amount,
            given_on=today,
            branch=advance.branch,
            method=advance.method,
            note=reason.strip(),
            cancels=advance,
            created_by=actor,
        )
        audit.record(
            actor,
            "salaries.advance.cancel",
            advance,
            after=audit.snapshot(cancel),
            branch_id=advance.branch_id,
            reason=reason,
        )
    return cancel


def _money(amount: int) -> str:
    from apps.core.money import format_som

    return format_som(amount)


def pay_out(
    *,
    actor,
    teacher,
    month: dt.date,
    paid_on: dt.date,
    branch=None,
    method=None,
    note: str = "",
) -> Payout:
    """Give the closed month's salary, minus advances, from a branch's Kassa (SPEC §24)."""
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
        if sheet.totals.to_pay <= 0:
            raise ValidationError(_("There is nothing to pay for this month."))
        _kassa(branch, method, paid_on)
        payout = Payout.objects.create(
            month=closed,
            teacher=teacher,
            amount=sheet.totals.to_pay,
            paid_on=paid_on,
            branch=branch,
            method=method,
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
        if payout.branch_id:  # paid from the Kassa: the money goes back in today
            _kassa(payout.branch, payout.method, dates.today())
        cancel = Payout.objects.create(
            month=payout.month,
            teacher=payout.teacher,
            kind=Payout.Kind.CANCEL,
            amount=payout.amount,
            paid_on=dates.today(),
            branch=payout.branch,
            method=payout.method,
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
