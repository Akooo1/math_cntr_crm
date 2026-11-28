"""Teacher salaries (docs/SPEC.md §13.2). Money in whole so'm (bigint)."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.model_fields import MoneyField


def _first_of_month(field: str, name: str) -> models.CheckConstraint:
    return models.CheckConstraint(condition=Q(**{f"{field}__day": 1}), name=name)


class Rate(models.Model):
    """A teacher's share from a month on. Append-only: a change is a new row."""

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="salary_rates",
        verbose_name=_("Teacher"),
    )
    rate_bp = models.PositiveIntegerField(_("Rate"))
    effective_from = models.DateField(_("Effective from"))
    reason = models.TextField(_("Reason"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "salaries_rate"
        verbose_name = _("Teacher rate")
        ordering = ["teacher_id", "-effective_from", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(rate_bp__lte=10_000), name="salaries_rate_bp_range"),
            _first_of_month("effective_from", "salaries_rate_first_of_month"),
        ]

    def __str__(self):
        return f"{self.teacher_id}: {self.rate_bp} from {self.effective_from}"


class StaffPay(models.Model):
    """A fixed monthly salary from a month on (administrators, sales managers; also a teacher
    who gets a fixed part). Append-only: a change is a new row; 0 stops the fixed pay."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fixed_pay",
        verbose_name=_("Employee"),
    )
    amount = MoneyField(_("Monthly salary"))
    effective_from = models.DateField(_("Effective from"))
    reason = models.TextField(_("Reason"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "salaries_staff_pay"
        verbose_name = _("Fixed salary")
        ordering = ["user_id", "-effective_from", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="salaries_staff_pay_amount"),
            _first_of_month("effective_from", "salaries_staff_pay_first_of_month"),
        ]

    def __str__(self):
        return f"{self.user_id}: {self.amount} from {self.effective_from}"


class Month(models.Model):
    """A closed salary month. Its lines are frozen. Append-only."""

    month = models.DateField(_("Month"), unique=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Closed by"),
    )
    closed_at = models.DateTimeField(_("Closed at"), auto_now_add=True)
    totals = models.JSONField(_("Totals"), default=dict)

    class Meta:
        db_table = "salaries_month"
        verbose_name = _("Salary month")
        ordering = ["-month"]
        constraints = [_first_of_month("month", "salaries_month_first_of_month")]

    def __str__(self):
        return f"{self.month:%Y-%m}"


class Line(models.Model):
    """One student's money in one group, frozen when the month closed. Append-only."""

    class Kind(models.TextChoices):
        SHARE = "share", _("Share")
        CORRECTION = "correction", _("Correction")

    month = models.ForeignKey(
        Month, on_delete=models.PROTECT, related_name="lines", verbose_name=_("Month")
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="salary_lines",
        verbose_name=_("Teacher"),
    )
    student = models.ForeignKey(
        "students.Student", on_delete=models.PROTECT, related_name="+", verbose_name=_("Student")
    )
    group = models.ForeignKey(
        "students.Group", on_delete=models.PROTECT, related_name="+", verbose_name=_("Group")
    )
    payment_month = models.DateField(_("Payment month"))
    kind = models.CharField(_("Type"), max_length=12, choices=Kind.choices)
    base = MoneyField(_("Money paid"))
    rate_bp = models.PositiveIntegerField(_("Rate"))
    amount = MoneyField(_("Amount"))

    class Meta:
        db_table = "salaries_line"
        verbose_name = _("Salary line")
        indexes = [models.Index(fields=["student", "group", "payment_month"])]
        constraints = [
            models.CheckConstraint(condition=~Q(base=0), name="salaries_line_base_nonzero"),
            models.CheckConstraint(
                condition=(Q(base__gt=0) & Q(amount__gte=0)) | (Q(base__lt=0) & Q(amount__lte=0)),
                name="salaries_line_amount_sign",
            ),
            models.CheckConstraint(
                condition=Q(rate_bp__lte=10_000), name="salaries_line_rate_range"
            ),
            _first_of_month("payment_month", "salaries_line_payment_month_first"),
        ]

    def __str__(self):
        return f"{self.teacher_id}/{self.student_id}: {self.amount}"


class FixedLine(models.Model):
    """An employee's fixed salary for a closed month (frozen at closing). Append-only."""

    month = models.ForeignKey(
        Month, on_delete=models.PROTECT, related_name="fixed_lines", verbose_name=_("Month")
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Employee"),
    )
    amount = MoneyField(_("Amount"))

    class Meta:
        db_table = "salaries_fixed_line"
        verbose_name = _("Fixed salary line")
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="salaries_fixed_line_positive"),
            models.UniqueConstraint(fields=["month", "user"], name="salaries_fixed_line_once"),
        ]

    def __str__(self):
        return f"{self.user_id}: {self.amount}"


class Adjustment(models.Model):
    """Bonus, deduction or carry-over. Deletable only while its month is open."""

    class Kind(models.TextChoices):
        BONUS = "bonus", _("Bonus")
        DEDUCTION = "deduction", _("Deduction")
        CARRY = "carry", _("Carried over from last month")

    month = models.DateField(_("Month"))
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="salary_adjustments",
        verbose_name=_("Teacher"),
    )
    kind = models.CharField(_("Type"), max_length=12, choices=Kind.choices)
    amount = MoneyField(_("Amount"))
    reason = models.TextField(_("Reason"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        related_name="+",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "salaries_adjustment"
        verbose_name = _("Bonus or deduction")
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(kind="bonus") & Q(amount__gt=0))
                | (Q(kind__in=["deduction", "carry"]) & Q(amount__lt=0)),
                name="salaries_adjustment_sign",
            ),
            _first_of_month("month", "salaries_adjustment_first_of_month"),
        ]

    def __str__(self):
        return f"{self.kind} {self.amount}"


class Payout(models.Model):
    """Cash handed to the teacher for a closed month. Append-only: a mistake is undone by a
    `cancel` row pointing at the payout."""

    class Kind(models.TextChoices):
        PAYOUT = "payout", _("Salary given")
        CANCEL = "cancel", _("Cancelled")

    month = models.ForeignKey(
        Month, on_delete=models.PROTECT, related_name="payouts", verbose_name=_("Month")
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="salary_payouts",
        verbose_name=_("Teacher"),
    )
    kind = models.CharField(_("Type"), max_length=10, choices=Kind.choices, default=Kind.PAYOUT)
    amount = MoneyField(_("Amount"))
    paid_on = models.DateField(_("Date"))
    # Paid from this branch's Kassa with this method (SPEC §24); empty on payouts made
    # before that, which stay outside the Kassa.
    branch = models.ForeignKey(
        "center_settings.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Branch"),
    )
    method = models.ForeignKey(
        "billing.PaymentMethod",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Payment method"),
    )
    note = models.TextField(_("Note"), blank=True)
    cancels = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cancelled_by",
        verbose_name=_("Cancels"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "salaries_payout"
        verbose_name = _("Salary payout")
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="salaries_payout_positive"),
            models.CheckConstraint(
                condition=(Q(kind="payout") & Q(cancels__isnull=True))
                | (Q(kind="cancel") & Q(cancels__isnull=False)),
                name="salaries_payout_cancel_link",
            ),
        ]

    def __str__(self):
        return f"{self.kind} {self.amount} {self.paid_on}"


class Advance(models.Model):
    """Maosh avansi: money given from a branch's Kassa before the month ends, taken off that
    month's salary (owner's request, SPEC §24). Append-only: a mistake is undone by a
    `cancel` row, dated the day it is cancelled, which puts the money back in the Kassa."""

    class Kind(models.TextChoices):
        ADVANCE = "advance", _("Salary advance")
        CANCEL = "cancel", _("Cancelled")

    person = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="salary_advances",
        verbose_name=_("Employee"),
    )
    month = models.DateField(_("Month"))  # first day of the month it is taken from
    kind = models.CharField(_("Type"), max_length=10, choices=Kind.choices, default=Kind.ADVANCE)
    amount = MoneyField(_("Amount"))
    given_on = models.DateField(_("Date"))
    branch = models.ForeignKey(
        "center_settings.Branch",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Branch"),
    )
    method = models.ForeignKey(
        "billing.PaymentMethod",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Payment method"),
    )
    note = models.TextField(_("Note"), blank=True)
    cancels = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cancelled_by",
        verbose_name=_("Cancels"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "salaries_advance"
        verbose_name = _("Salary advance")
        verbose_name_plural = _("Salary advances")
        ordering = ["given_on", "created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="salaries_advance_positive"),
            models.CheckConstraint(
                condition=(Q(kind="advance") & Q(cancels__isnull=True))
                | (Q(kind="cancel") & Q(cancels__isnull=False)),
                name="salaries_advance_cancel_link",
            ),
        ]

    def __str__(self):
        return f"{self.kind} {self.amount} {self.given_on}"
