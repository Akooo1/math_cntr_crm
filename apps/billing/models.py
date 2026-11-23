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
