"""Expense writes (docs/SPEC.md §20). Every write is audited.

An expense paid from the cash desk lowers that day's Kassa, so it follows the payment
rules: not in the future, within the backdating window, never on a closed day (checked
under the day lock, and the Kassa close sees it through the cash-source hook)."""

import datetime as dt

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.billing import selectors as billing_selectors
from apps.billing.services.cash import lock_day
from apps.core import audit, dates
from apps.core.permissions import ensure_branch_access, has_perm, require_perm
from apps.core.system_settings import get_setting

from .models import Category, Expense


def _check_cash_day(branch_id: int, day: dt.date) -> None:
    lock_day(branch_id, day)
    if billing_selectors.is_day_closed(branch_id, day):
        raise ValidationError(_("This day is closed in the Kassa. Choose another date."))


def record(
    *,
    actor,
    branch,
    category: Category,
    amount: int,
    spent_on: dt.date,
    method=None,
    note: str = "",
) -> Expense:
    """`branch` None = center-wide (Direktor only); `method` = paid from that branch's cash
    desk with this method (None = outside the Kassa)."""
    require_perm(actor, "expenses.create")
    if branch is None:
        if not has_perm(actor, "expenses.shared"):
            raise PermissionDenied
        if method is not None:
            raise ValidationError(
                _("A center-wide expense can't come from a branch cash desk. Choose the branch.")
            )
    else:
        ensure_branch_access(actor, branch.pk)
    if amount <= 0:
        raise ValidationError(_("Enter an amount greater than zero."))
    if not category.is_active:
        raise ValidationError(_("Choose a category from the list."))
    today = dates.today()
    if spent_on > today:
        raise ValidationError(_("The date can't be in the future."))
    if method is not None:
        if not method.included_in_cash_close or not method.is_active:
            raise ValidationError(_("Choose a cash desk method."))
        window = get_setting("billing.backdate_days")
        if (today - spent_on).days > window:
            raise ValidationError(
                _("A cash desk expense can be dated at most %(n)s days back.") % {"n": window}
            )
    with transaction.atomic():
        if method is not None:
            _check_cash_day(branch.pk, spent_on)
        expense = Expense.objects.create(
            branch=branch,
            category=category,
            amount=amount,
            spent_on=spent_on,
            method=method,
            note=note.strip(),
            created_by=actor,
        )
        audit.record(
            actor,
            "expenses.expense.create",
            expense,
            after=audit.snapshot(expense),
            branch_id=branch.pk if branch else None,
        )
    return expense


def reverse(*, actor, expense: Expense, reason: str) -> Expense:
    """Cancel an expense (Direktor only): a reversal row dated today. A cash desk expense's
    money goes back into today's Kassa."""
    require_perm(actor, "expenses.reverse")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError(_("Write the reason."))
    today = dates.today()
    with transaction.atomic():
        expense = Expense.objects.select_for_update().get(pk=expense.pk)
        if expense.kind != Expense.Kind.EXPENSE:
            raise ValidationError(_("Only an expense can be cancelled."))
        if Expense.objects.filter(reverses=expense).exists():
            raise ValidationError(_("This expense is already cancelled."))
        if expense.method_id:
            _check_cash_day(expense.branch_id, today)
        reversal = Expense.objects.create(
            kind=Expense.Kind.REVERSAL,
            branch=expense.branch,
            category=expense.category,
            amount=expense.amount,
            spent_on=today,
            method=expense.method,
            reverses=expense,
            reason=reason,
            created_by=actor,
        )
        audit.record(
            actor,
            "expenses.expense.reverse",
            expense,
            after=audit.snapshot(reversal),
            branch_id=expense.branch_id,
            reason=reason,
        )
    return reversal
