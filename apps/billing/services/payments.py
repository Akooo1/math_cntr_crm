"""Payments, reversals (storno) and refunds (docs/SPEC.md 6.4.5, 6.4.8, 6.4.9)."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import IntegrityError, InternalError, transaction
from django.utils.translation import gettext as _

from apps.core import audit, dates, events
from apps.core.permissions import ensure_branch_access, require_perm
from apps.core.system_settings import get_setting
from apps.settings.models import Branch
from apps.students.models import Student

from ..events import PaymentRecorded, PaymentReversed, RefundIssued
from ..models import CashDayClose, Payment, PaymentMethod, ReceiptCounter, StudentBalance
from ..providers import get_provider
from .allocation import rebuild_for_student
from .cash import lock_day


def next_receipt(branch: Branch) -> tuple[int, str]:
    """Gapless per-branch number under a row lock (SPEC Q-15)."""
    ReceiptCounter.objects.bulk_create([ReceiptCounter(branch=branch)], ignore_conflicts=True)
    counter = ReceiptCounter.objects.select_for_update().get(branch=branch)
    counter.last_seq += 1
    counter.save(update_fields=["last_seq"])
    return counter.last_seq, f"{branch.receipt_prefix}-{counter.last_seq:06d}"


def is_closed(branch_id: int, day: dt.date) -> bool:
    return CashDayClose.objects.in_force().filter(branch_id=branch_id, date=day).exists()


def _check_day(branch_id: int, day: dt.date, method: PaymentMethod):
    """Call inside the transaction: takes the cash-day lock, then checks the close."""
    if method.included_in_cash_close:
        lock_day(branch_id, day)
    if method.included_in_cash_close and is_closed(branch_id, day):
        raise ValidationError(
            _("The cash day %(day)s is closed.") % {"day": dates.format_date(day)}
        )


def _insert(**fields) -> Payment:
    """Insert, turning the database's closed-day trigger into a readable error."""
    try:
        with transaction.atomic():
            return Payment.objects.create(**fields)
    except (InternalError, IntegrityError) as exc:
        if "closed" in str(exc):
            raise ValidationError(_("The cash day is closed.")) from exc
        raise


def record_payment(
    *,
    actor,
    student: Student,
    amount: int,
    method: PaymentMethod,
    paid_on: dt.date,
    comment: str = "",
    branch: Branch | None = None,
) -> Payment:
    require_perm(actor, "billing.payment.create")
    branch = branch or student.branch
    ensure_branch_access(actor, branch.pk)
    ensure_branch_access(actor, student.branch_id)
    if amount <= 0:
        raise ValidationError(_("The amount must be positive."))
    provider = get_provider(method.provider_code)
    if provider.is_system or provider.is_online or not method.is_active:
        raise ValidationError(_("This payment method can't be used here."))
    today = dates.today()
    if paid_on > today:
        raise ValidationError(_("The payment date can't be in the future."))
    window = get_setting("billing.backdate_days")
    if (today - paid_on).days > window:
        raise ValidationError(_("The payment date can be at most %(n)d days back.") % {"n": window})
    with transaction.atomic():
        _check_day(branch.pk, paid_on, method)
        seq, number = next_receipt(branch)
        payment = _insert(
            student=student,
            branch=branch,
            kind=Payment.Kind.PAYMENT,
            amount=amount,
            method=method,
            provider_code=method.provider_code,
            paid_on=paid_on,
            received_by=actor,
            comment=comment.strip(),
            receipt_seq=seq,
            receipt_number=number,
        )
        rebuild_for_student(student.pk)
        audit.record(actor, "billing.payment.create", payment, after=audit.snapshot(payment))
        events.publish(
            PaymentRecorded(
                payment_id=payment.pk, student_id=student.pk, branch_id=branch.pk, amount=amount
            )
        )
    return payment


def reverse_payment(*, actor, payment: Payment, reason: str) -> Payment:
    """Cancel a whole payment entered by mistake. Dated today (SPEC 6.4.8)."""
    require_perm(actor, "billing.reverse")
    ensure_branch_access(actor, payment.branch_id)
    if not reason.strip():
        raise ValidationError(_("Write the reason."))
    today = dates.today()
    with transaction.atomic():
        original = Payment.objects.select_for_update().get(pk=payment.pk)
        if original.kind != Payment.Kind.PAYMENT or original.status != Payment.Status.CONFIRMED:
            raise ValidationError(_("Only a confirmed payment can be reversed."))
        if Payment.objects.filter(reverses=original).exists():
            raise ValidationError(_("This payment is already reversed."))
        _check_day(original.branch_id, today, original.method)
        seq, number = next_receipt(original.branch)
        reversal = _insert(
            student=original.student,
            branch=original.branch,
            kind=Payment.Kind.REVERSAL,
            amount=original.amount,
            method=original.method,
            provider_code=original.provider_code,
            paid_on=today,
            received_by=actor,
            reverses=original,
            reason=reason.strip(),
            receipt_seq=seq,
            receipt_number=number,
        )
        rebuild_for_student(original.student_id)
        audit.record(
            actor,
            "billing.payment.reverse",
            original,
            after={"reversal": reversal.receipt_number, "amount": original.amount},
            reason=reason.strip(),
            only_changes=False,
        )
        events.publish(PaymentReversed(payment_id=original.pk, reversal_id=reversal.pk))
    return reversal


def credit_of(student_id: int) -> int:
    row = StudentBalance.objects.filter(pk=student_id).first()
    return max(row.balance, 0) if row else 0


def refund(*, actor, student: Student, amount: int, method: PaymentMethod, reason: str) -> Payment:
    """Pay money back. Only the credit (avans) can be refunded (SPEC 6.4.8)."""
    require_perm(actor, "billing.reverse")
    return _refund(actor=actor, student=student, amount=amount, method=method, reason=reason)


def leave_refundable(enrollment) -> int:
    """What can still be paid back for the lessons not taken after leaving this group: what
    the leave took off its charges, minus refunds already made for it, never more than the
    student's credit (SPEC §24). Absences never count: a missed lesson is still paid."""
    from django.db.models import Sum

    from ..models import ChargeAdjustment

    if enrollment.status != "left":
        return 0
    taken_off = -int(
        ChargeAdjustment.objects.filter(
            charge__enrollment=enrollment,
            kind__in=(ChargeAdjustment.Kind.PRORATION_LEAVE, ChargeAdjustment.Kind.CANCELLATION),
        ).aggregate(t=Sum("amount"))["t"]
        or 0
    )
    refunded = int(
        Payment.objects.filter(
            for_enrollment=enrollment, kind=Payment.Kind.REFUND, reversed_by__isnull=True
        ).aggregate(t=Sum("amount"))["t"]
        or 0
    )
    return max(0, min(taken_off - refunded, credit_of(enrollment.student_id)))


def refund_on_leave(*, actor, enrollment, amount: int, method: PaymentMethod) -> Payment:
    """Pay back the lessons not taken when a student leaves a group. Administrators may do
    this one refund (owner's decision, SPEC §24); every other refund stays the Direktor's.
    Only from the Kassa (a cash desk method), only up to leave_refundable()."""
    require_perm(actor, "billing.refund.leave")
    if not method.included_in_cash_close:
        raise ValidationError(_("Choose a cash desk method."))
    with transaction.atomic():
        Student.objects.select_for_update().get(pk=enrollment.student_id)
        limit = leave_refundable(enrollment)
        if amount > limit:
            raise ValidationError(
                _("At most %(amount)s can be returned for this group.")
                % {"amount": money_text(limit)}
            )
        reason = _("Left the group %(group)s: lessons not taken") % {"group": enrollment.group.name}
        return _refund(
            actor=actor,
            student=enrollment.student,
            amount=amount,
            method=method,
            reason=reason,
            for_enrollment=enrollment,
        )


def _refund(*, actor, student, amount, method, reason, for_enrollment=None) -> Payment:
    ensure_branch_access(actor, student.branch_id)
    if not reason.strip():
        raise ValidationError(_("Write the reason."))
    if amount <= 0:
        raise ValidationError(_("The amount must be positive."))
    if get_provider(method.provider_code).is_system:
        raise ValidationError(_("This payment method can't be used here."))
    today = dates.today()
    with transaction.atomic():
        Student.objects.select_for_update().get(pk=student.pk)
        credit = credit_of(student.pk)
        if amount > credit:
            raise ValidationError(
                _("Only the credit can be refunded: %(credit)s.") % {"credit": money_text(credit)}
            )
        _check_day(student.branch_id, today, method)
        seq, number = next_receipt(student.branch)
        row = _insert(
            student=student,
            branch=student.branch,
            kind=Payment.Kind.REFUND,
            amount=amount,
            method=method,
            provider_code=method.provider_code,
            paid_on=today,
            received_by=actor,
            reason=reason.strip(),
            receipt_seq=seq,
            receipt_number=number,
            for_enrollment=for_enrollment,
        )
        rebuild_for_student(student.pk)
        audit.record(
            actor, "billing.payment.refund", row, after=audit.snapshot(row), reason=reason.strip()
        )
        events.publish(RefundIssued(payment_id=row.pk, student_id=student.pk, amount=amount))
    return row


def money_text(amount: int) -> str:
    from apps.core.money import format_som

    return format_som(amount)
