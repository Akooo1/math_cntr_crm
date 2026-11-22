from django.conf import settings as dj_settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class Branch(models.Model):
    name = models.CharField(_("Name"), max_length=100, unique=True)
    address = models.CharField(_("Address"), max_length=255, blank=True)
    phone = models.CharField(_("Phone"), max_length=13, blank=True)
    receipt_prefix = models.CharField(
        _("Receipt prefix"),
        max_length=5,
        unique=True,
        validators=[RegexValidator(r"^[A-Z]{1,5}$", _("1 to 5 capital Latin letters."))],
        help_text=_("Receipt numbers look like CH-000123."),
    )
    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "center_branch"
        ordering = ["name"]
        verbose_name = _("Branch")
        verbose_name_plural = _("Branches")

    def __str__(self):
        return self.name


class UserBranch(models.Model):
    """Which branches a staff member works in. Table name per docs/SPEC.md 5.2.

    Lives in the settings app because accounts sits below settings in the module graph.
    """

    user = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="branch_links"
    )
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="user_links")

    class Meta:
        db_table = "accounts_user_branch"
        constraints = [models.UniqueConstraint(fields=["user", "branch"], name="uniq_user_branch")]

    def __str__(self):
        return f"{self.user_id}:{self.branch_id}"


class Room(models.Model):
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name="rooms", verbose_name=_("Branch")
    )
    name = models.CharField(_("Name"), max_length=100)
    capacity = models.PositiveIntegerField(
        _("Capacity"), validators=[MinValueValidator(1)], default=12
    )
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        db_table = "center_room"
        ordering = ["branch__name", "name"]
        verbose_name = _("Room")
        verbose_name_plural = _("Rooms")
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="uniq_room_name_per_branch",
                violation_error_message=_("This branch already has a room with this name."),
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.branch.name})"


class Course(models.Model):
    class PricingModel(models.TextChoices):
        MONTHLY = "monthly", _("Monthly fee")
        INSTALLMENT = "installment", _("Installments")

    name = models.CharField(_("Name"), max_length=150, unique=True)
    pricing_model = models.CharField(
        _("Pricing model"), max_length=20, choices=PricingModel.choices
    )
    duration_months = models.PositiveIntegerField(
        _("Duration (months)"), null=True, blank=True, validators=[MinValueValidator(1)]
    )
    description = models.TextField(_("Description"), blank=True)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        db_table = "center_course"
        ordering = ["name"]
        verbose_name = _("Course")
        verbose_name_plural = _("Courses")

    def __str__(self):
        return self.name

    @property
    def is_monthly(self) -> bool:
        return self.pricing_model == self.PricingModel.MONTHLY


class CenterInfo(models.Model):
    """Single row: the center's name and receipt details."""

    center_name = models.CharField(_("Center name"), max_length=150)
    legal_name = models.CharField(_("Legal name"), max_length=200, blank=True)
    inn = models.CharField(
        _("Tax ID (STIR)"),
        max_length=9,
        blank=True,
        validators=[RegexValidator(r"^\d{9}$", _("The tax ID has 9 digits."))],
    )
    bank_details = models.TextField(_("Bank details"), blank=True)
    phone = models.CharField(_("Phone"), max_length=13, blank=True)
    receipt_footer = models.CharField(_("Receipt footer text"), max_length=255, blank=True)

    class Meta:
        db_table = "center_info"
        verbose_name = _("Center details")
        verbose_name_plural = _("Center details")

    def __str__(self):
        return self.center_name


class BranchReceiptInfo(models.Model):
    """Optional per-branch override of the receipt details."""

    branch = models.OneToOneField(
        Branch, on_delete=models.PROTECT, related_name="receipt_info", verbose_name=_("Branch")
    )
    legal_name = models.CharField(_("Legal name"), max_length=200, blank=True)
    inn = models.CharField(
        _("Tax ID (STIR)"),
        max_length=9,
        blank=True,
        validators=[RegexValidator(r"^\d{9}$", _("The tax ID has 9 digits."))],
    )
    address = models.CharField(_("Address"), max_length=255, blank=True)
    phone = models.CharField(_("Phone"), max_length=13, blank=True)
    footer = models.CharField(_("Receipt footer text"), max_length=255, blank=True)

    class Meta:
        db_table = "center_branch_receipt_info"
        verbose_name = _("Branch receipt details")
        verbose_name_plural = _("Branch receipt details")

    def __str__(self):
        return str(self.branch)
