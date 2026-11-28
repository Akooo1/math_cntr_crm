from django.conf import settings as dj_settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.model_fields import MoneyField
from apps.settings.models import Branch, Course


class Price(models.Model):
    """Immutable price row. A change is a new row with a new effective date (SPEC 5.6).

    Rows are never updated or deleted (database trigger). This table is the price history.
    Scope: group > branch > course (all branches).
    """

    class Kind(models.TextChoices):
        MONTHLY = "monthly", _("Monthly fee")
        FULL_COURSE = "full_course", _("Full course price")

    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="prices", verbose_name=_("Course")
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Branch"),
        help_text=_("Leave empty for all branches."),
    )
    group = models.ForeignKey(
        "students.Group",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Group"),
        help_text=_("Only for a special price in one group."),
    )
    kind = models.CharField(_("Price type"), max_length=20, choices=Kind.choices)
    amount = MoneyField(_("Amount"))
    effective_from = models.DateField(_("Effective from"))
    note = models.CharField(_("Note"), max_length=255, blank=True)
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "billing_price"
        ordering = ["course__name", "-effective_from", "-created_at"]
        verbose_name = _("Price")
        verbose_name_plural = _("Prices")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="price_amount_positive",
                violation_error_message=_("The amount must be positive."),
            )
        ]

    def __str__(self):
        return f"{self.course} {self.amount}"


class InstallmentTemplate(models.Model):
    class SplitMode(models.TextChoices):
        EQUAL = "equal", _("Equal parts")
        CUSTOM = "custom", _("Custom shares")

    class FirstDue(models.TextChoices):
        ON_START = "on_start", _("On the start date")
        FIXED_DAY = "fixed_day", _("On a fixed day of the month")

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="installment_templates",
        verbose_name=_("Course"),
        help_text=_("Leave empty to allow it for every installment course."),
    )
    name = models.CharField(_("Name"), max_length=150)
    parts_count = models.PositiveIntegerField(
        _("Number of parts"), validators=[MinValueValidator(2), MaxValueValidator(24)]
    )
    split_mode = models.CharField(
        _("Split"), max_length=10, choices=SplitMode.choices, default=SplitMode.EQUAL
    )
    first_due = models.CharField(
        _("First part due"), max_length=10, choices=FirstDue.choices, default=FirstDue.ON_START
    )
    interval_months = models.PositiveIntegerField(
        _("Months between parts"),
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    due_day_of_month = models.PositiveIntegerField(
        _("Due day of the month"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text=_("Required for a fixed day. Optional otherwise: parts 2+ fall on this day."),
    )
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        db_table = "billing_installment_template"
        ordering = ["name"]
        verbose_name = _("Installment template")
        verbose_name_plural = _("Installment templates")

    def __str__(self):
        return self.name

    def shares_bp(self) -> list[int]:
        return list(self.parts.order_by("part_no").values_list("share_bp", flat=True))


class InstallmentTemplatePart(models.Model):
    template = models.ForeignKey(
        InstallmentTemplate, on_delete=models.CASCADE, related_name="parts"
    )
    part_no = models.PositiveIntegerField()
    share_bp = models.PositiveIntegerField(validators=[MaxValueValidator(10000)])

    class Meta:
        db_table = "billing_installment_template_part"
        ordering = ["template", "part_no"]
        constraints = [
            models.UniqueConstraint(fields=["template", "part_no"], name="uniq_template_part")
        ]

    def __str__(self):
        return f"{self.template_id}#{self.part_no}"


class DiscountType(models.Model):
    class Kind(models.TextChoices):
        PERCENT = "percent", _("Percent")
        FIXED = "fixed", _("Fixed amount")

    class AppliesTo(models.TextChoices):
        MONTHLY = "monthly", _("Monthly courses")
        INSTALLMENT = "installment", _("Installment courses")
        ANY = "any", _("All courses")

    name = models.CharField(_("Name"), max_length=150, unique=True)
    kind = models.CharField(_("Discount type"), max_length=10, choices=Kind.choices)
    value = models.BigIntegerField(
        _("Value"), help_text=_("Percent in basis points (10% = 1000) or an amount in so'm.")
    )
    applies_to = models.CharField(
        _("Applies to"), max_length=15, choices=AppliesTo.choices, default=AppliesTo.ANY
    )
    allow_custom_value = models.BooleanField(_("Director may enter a custom value"), default=False)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        db_table = "billing_discount_type"
        ordering = ["name"]
        verbose_name = _("Discount type")
        verbose_name_plural = _("Discount types")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(value__gt=0),
                name="discount_value_positive",
                violation_error_message=_("The value must be positive."),
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="percent") | models.Q(value__lte=10000),
                name="discount_percent_max_100",
                violation_error_message=_("A percent must be above 0 and at most 100."),
            ),
        ]

    def __str__(self):
        return self.name


class PaymentMethod(models.Model):
    name = models.CharField(_("Name"), max_length=100, unique=True)
    provider_code = models.CharField(_("Provider"), max_length=30, default="manual")
    included_in_cash_close = models.BooleanField(
        _("Counted in the daily cash report"), default=True
    )
    is_active = models.BooleanField(_("Active"), default=True)
    sort_order = models.PositiveIntegerField(_("Order"), default=100)

    class Meta:
        db_table = "billing_payment_method"
        ordering = ["sort_order", "name"]
        verbose_name = _("Payment method")
        verbose_name_plural = _("Payment methods")

    def __str__(self):
        return self.name

    @property
    def is_system(self) -> bool:
        from .providers import get_provider

        return get_provider(self.provider_code).is_system


# =========================================================================================
# Assignments and plans (mutable, audited)
# =========================================================================================


class DiscountAssignment(models.Model):
    """A discount given to one enrollment for a date range (SPEC 6.4.4).

    Assigning or ending one never changes charges already issued.
    """

    enrollment = models.ForeignKey(
        "students.Enrollment",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Group"),
    )
    discount_type = models.ForeignKey(
        DiscountType,
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name=_("Discount type"),
    )
    value = models.BigIntegerField(_("Value"))  # snapshot (or custom value) in bp or so'm
    valid_from = models.DateField(_("From"))
    valid_to = models.DateField(_("To"), null=True, blank=True)
    reason = models.TextField(_("Reason"), blank=True)
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ended_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "billing_discount_assignment"
        ordering = ["-valid_from", "-id"]
        verbose_name = _("Discount")
        verbose_name_plural = _("Discounts")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(value__gt=0), name="discount_assignment_value_positive"
            )
        ]

    def __str__(self):
        return str(self.discount_type)

    @property
    def kind(self) -> str:
        return self.discount_type.kind


class InstallmentPlan(models.Model):
    enrollment = models.OneToOneField(
        "students.Enrollment",
        on_delete=models.PROTECT,
        related_name="installment_plan",
        verbose_name=_("Group"),
    )
    template = models.ForeignKey(
        InstallmentTemplate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Installment template"),
    )
    template_snapshot = models.JSONField(default=dict)
    full_price = MoneyField(_("Course price"))
    price = models.ForeignKey(
        Price, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_installment_plan"
        verbose_name = _("Installment plan")
        verbose_name_plural = _("Installment plans")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(full_price__gte=0), name="plan_full_price_nonnegative"
            )
        ]

    def __str__(self):
        return f"{self.enrollment_id}"


class InstallmentPlanRevision(models.Model):
    plan = models.ForeignKey(InstallmentPlan, on_delete=models.PROTECT, related_name="revisions")
    reason = models.TextField(_("Reason"))
    before = models.JSONField()
    after = models.JSONField()
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_installment_plan_revision"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.plan_id}@{self.created_at}"


# =========================================================================================
# Ledger (append-only; database triggers reject UPDATE and DELETE)
# =========================================================================================


class Charge(models.Model):
    """Hisoblangan. Never edited: changes are ChargeAdjustment rows (SPEC 5.6)."""

    class Kind(models.TextChoices):
        MONTHLY = "monthly", _("Monthly fee")
        INSTALLMENT = "installment", _("Installment part")
        OPENING_BALANCE = "opening_balance", _("Opening balance")
        MANUAL = "manual", _("Additional charge")

    student = models.ForeignKey(
        "students.Student", on_delete=models.PROTECT, related_name="+", verbose_name=_("Student")
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name="+", verbose_name=_("Branch")
    )
    enrollment = models.ForeignKey(
        "students.Enrollment", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    group = models.ForeignKey(
        "students.Group",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Group"),
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Course"),
    )
    kind = models.CharField(_("Type"), max_length=20, choices=Kind.choices)
    period_month = models.DateField(_("Month"), null=True, blank=True)
    plan = models.ForeignKey(
        InstallmentPlan, on_delete=models.PROTECT, null=True, blank=True, related_name="charges"
    )
    part_no = models.PositiveIntegerField(_("Part"), null=True, blank=True)
    due_date = models.DateField(_("Due date"), db_index=True)
    base_amount = MoneyField(_("List price"))
    suggested_amount = MoneyField(_("Suggested amount"), null=True, blank=True)
    amount = MoneyField(_("Amount"))
    override_reason = models.TextField(_("Reason for a different amount"), blank=True)
    price = models.ForeignKey(
        Price, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    description = models.CharField(_("Description"), max_length=255, blank=True)
    import_batch = models.ForeignKey(
        "students.ImportBatch", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(  # null = the monthly job
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "billing_charge"
        ordering = ["due_date", "created_at", "id"]
        verbose_name = _("Charge")
        verbose_name_plural = _("Charges")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="charge_amount_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(base_amount__gte=0), name="charge_base_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(suggested_amount__isnull=True)
                | models.Q(amount=models.F("suggested_amount"))
                | ~models.Q(override_reason=""),
                name="charge_override_needs_reason",
                violation_error_message=_("A different amount needs a reason."),
            ),
            models.UniqueConstraint(
                fields=["enrollment", "period_month"],
                condition=models.Q(kind="monthly"),
                name="uniq_monthly_charge_per_enrollment",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.due_date}"


class ChargeDiscount(models.Model):
    charge = models.ForeignKey(Charge, on_delete=models.PROTECT, related_name="discounts")
    assignment = models.ForeignKey(
        DiscountAssignment, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    discount_type = models.ForeignKey(DiscountType, on_delete=models.PROTECT, related_name="+")
    name_snapshot = models.CharField(_("Discount"), max_length=150)
    kind = models.CharField(max_length=10, choices=DiscountType.Kind.choices)
    value = models.BigIntegerField()
    amount = MoneyField(_("Amount"))

    class Meta:
        db_table = "billing_charge_discount"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="charge_discount_nonnegative"
            )
        ]

    def __str__(self):
        return self.name_snapshot


class ChargeAdjustment(models.Model):
    class Kind(models.TextChoices):
        PRORATION_LEAVE = "proration_leave", _("Left the group")
        PRORATION_FREEZE = "proration_freeze", _("Freeze")
        PRORATION_JOIN = "proration_join", _("Back from freeze")
        MOVE = "move", _("Moved to another group")
        PLAN_EDIT = "plan_edit", _("Installment plan changed")
        CANCELLATION = "cancellation", _("Cancelled")
        CORRECTION = "correction", _("Correction")

    charge = models.ForeignKey(Charge, on_delete=models.PROTECT, related_name="adjustments")
    amount = models.BigIntegerField(_("Amount"))  # signed
    kind = models.CharField(_("Type"), max_length=20, choices=Kind.choices)
    suggested_amount = models.BigIntegerField(_("Suggested amount"), null=True, blank=True)
    reason = models.TextField(_("Reason"), blank=True)
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_charge_adjustment"
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(suggested_amount__isnull=True)
                | models.Q(amount=models.F("suggested_amount"))
                | ~models.Q(reason=""),
                name="adjustment_override_needs_reason",
            )
        ]

    def __str__(self):
        return f"{self.charge_id}:{self.amount}"


class Payment(models.Model):
    """To'lov, its reversal (storno) or a refund. Rows are never edited or deleted."""

    class Kind(models.TextChoices):
        PAYMENT = "payment", _("Payment")
        REVERSAL = "reversal", _("Reversal")
        REFUND = "refund", _("Refund")

    class Status(models.TextChoices):
        CONFIRMED = "confirmed", _("Confirmed")
        PENDING = "pending", _("Pending")

    student = models.ForeignKey(
        "students.Student", on_delete=models.PROTECT, related_name="+", verbose_name=_("Student")
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name="+", verbose_name=_("Branch")
    )
    kind = models.CharField(_("Type"), max_length=10, choices=Kind.choices, default=Kind.PAYMENT)
    amount = MoneyField(_("Amount"))
    method = models.ForeignKey(
        PaymentMethod, on_delete=models.PROTECT, related_name="+", verbose_name=_("Payment method")
    )
    provider_code = models.CharField(max_length=30, default="manual")
    external_id = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001 - unique if set
    status = models.CharField(
        _("Status"), max_length=10, choices=Status.choices, default=Status.CONFIRMED
    )
    paid_on = models.DateField(_("Date"), db_index=True)
    received_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Received by"),
    )
    comment = models.CharField(_("Comment"), max_length=255, blank=True)
    reverses = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversed_by"
    )
    reason = models.TextField(_("Reason"), blank=True)
    receipt_seq = models.PositiveIntegerField()
    receipt_number = models.CharField(_("Receipt"), max_length=20)
    import_batch = models.ForeignKey(
        "students.ImportBatch", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "billing_payment"
        ordering = ["-paid_on", "-created_at", "-id"]
        verbose_name = _("Payment")
        verbose_name_plural = _("Payments")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="payment_amount_positive"
            ),
            models.UniqueConstraint(
                fields=["branch", "receipt_seq"], name="uniq_receipt_per_branch"
            ),
            models.UniqueConstraint(
                fields=["provider_code", "external_id"],
                condition=models.Q(external_id__isnull=False),
                name="uniq_provider_external_id",
            ),
            models.CheckConstraint(
                condition=models.Q(kind="payment") | ~models.Q(reason=""),
                name="reversal_refund_need_reason",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="reversal") | models.Q(reverses__isnull=False),
                name="reversal_points_to_payment",
            ),
        ]

    def __str__(self):
        return self.receipt_number

    @property
    def signed_amount(self) -> int:
        """Effect on the student's account: + money in, - money out."""
        return self.amount if self.kind == self.Kind.PAYMENT else -self.amount


class ReceiptCounter(models.Model):
    branch = models.OneToOneField(
        Branch, on_delete=models.PROTECT, primary_key=True, related_name="+"
    )
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "billing_receipt_counter"

    def __str__(self):
        return f"{self.branch_id}:{self.last_seq}"


class CashDayCloseQuerySet(models.QuerySet):
    def in_force(self):
        """Closes that still lock their day: not undone by a reopen (SPEC §24)."""
        return self.filter(reopen__isnull=True)


class CashDayClose(models.Model):
    """A closed branch-day. Rows are never edited or deleted; a reopen (CashDayReopen)
    undoes one, and closing the day again adds a new row with a new snapshot."""

    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name="+", verbose_name=_("Branch")
    )
    date = models.DateField(_("Date"))
    closed_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Closed by"),
    )
    closed_at = models.DateTimeField(_("Closed at"), auto_now_add=True)
    totals = models.JSONField(default=dict)
    note = models.CharField(_("Note"), max_length=255, blank=True)

    objects = CashDayCloseQuerySet.as_manager()

    class Meta:
        db_table = "billing_cash_day_close"
        ordering = ["-date"]
        verbose_name = _("Closed cash day")
        verbose_name_plural = _("Closed cash days")
        indexes = [models.Index(fields=["branch", "date"], name="cash_close_branch_date")]

    def __str__(self):
        return f"{self.branch_id}:{self.date}"


class CashDayReopen(models.Model):
    """The Direktor reopened a closed day, with a reason (owner's request, SPEC §24)."""

    close = models.OneToOneField(
        CashDayClose, on_delete=models.PROTECT, related_name="reopen", verbose_name=_("Close")
    )
    reopened_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Reopened by"),
    )
    reopened_at = models.DateTimeField(_("Reopened at"), auto_now_add=True)
    reason = models.TextField(_("Reason"))

    class Meta:
        db_table = "billing_cash_day_reopen"
        ordering = ["-reopened_at"]
        verbose_name = _("Reopened cash day")
        verbose_name_plural = _("Reopened cash days")
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="cash_reopen_reason_required"
            )
        ]

    def __str__(self):
        return f"{self.close_id}"


# =========================================================================================
# Derived data
# =========================================================================================


class Allocation(models.Model):
    """Derived cache: which payment paid which charge (FIFO). Rebuilt per student by
    services.allocation.rebuild_for_student(); never edited by hand."""

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="allocations")
    charge = models.ForeignKey(Charge, on_delete=models.CASCADE, related_name="allocations")
    amount = MoneyField()

    class Meta:
        db_table = "billing_allocation"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="allocation_positive")
        ]

    def __str__(self):
        return f"{self.payment_id}->{self.charge_id}:{self.amount}"


class ChargeNet(models.Model):
    """Read-only view billing_charge_net: net = amount - discounts + adjustments."""

    charge = models.OneToOneField(
        Charge,
        on_delete=models.DO_NOTHING,
        primary_key=True,
        db_column="charge_id",
        related_name="net_row",
    )
    student = models.ForeignKey("students.Student", on_delete=models.DO_NOTHING, related_name="+")
    branch = models.ForeignKey(Branch, on_delete=models.DO_NOTHING, related_name="+")
    group = models.ForeignKey(
        "students.Group", on_delete=models.DO_NOTHING, null=True, related_name="+"
    )
    course = models.ForeignKey(Course, on_delete=models.DO_NOTHING, null=True, related_name="+")
    enrollment = models.ForeignKey(
        "students.Enrollment", on_delete=models.DO_NOTHING, null=True, related_name="+"
    )
    kind = models.CharField(max_length=20)
    due_date = models.DateField()
    period_month = models.DateField(null=True)
    net = models.BigIntegerField()
    paid = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = "billing_charge_net"

    def __str__(self):
        return f"{self.charge_id}:{self.net}"

    @property
    def open(self) -> int:
        return self.net - self.paid


class StudentBalance(models.Model):
    """Read-only view billing_student_balance. Negative = debt, positive = credit (avans)."""

    student = models.OneToOneField(
        "students.Student",
        on_delete=models.DO_NOTHING,
        primary_key=True,
        db_column="student_id",
        related_name="+",
    )
    paid = models.BigIntegerField()
    charged = models.BigIntegerField()
    balance = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = "billing_student_balance"

    def __str__(self):
        return f"{self.student_id}:{self.balance}"
