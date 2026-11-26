"""Expenses (docs/SPEC.md §20). Money in whole so'm. Append-only: a mistake is undone with
a reversal row, like payments."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.model_fields import MoneyField


class Category(models.Model):
    name = models.CharField(_("Name"), max_length=100, unique=True)
    sort_order = models.PositiveIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        db_table = "expenses_category"
        ordering = ["sort_order", "name"]
        verbose_name = _("Expense category")
        verbose_name_plural = _("Expense categories")

    def __str__(self):
        return self.name


class Expense(models.Model):
    class Kind(models.TextChoices):
        EXPENSE = "expense", _("Expense")
        REVERSAL = "reversal", _("Cancelled")

    kind = models.CharField(_("Type"), max_length=10, choices=Kind.choices, default=Kind.EXPENSE)
    # Empty = a center-wide expense (split between branches in the profit report).
    branch = models.ForeignKey(
        "center_settings.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Branch"),
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="expenses", verbose_name=_("Category")
    )
    amount = MoneyField(_("Amount"))
    spent_on = models.DateField(_("Date"))
    # Paid from the branch's cash desk with this method (lowers the Kassa); empty = paid
    # outside the Kassa (bank transfer, the owner's own money).
    method = models.ForeignKey(
        "billing.PaymentMethod",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Paid from the cash desk"),
    )
    note = models.TextField(_("Note"), blank=True)
    reverses = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversed_by",
        verbose_name=_("Cancels"),
    )
    reason = models.TextField(_("Reason"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "expenses_expense"
        ordering = ["-spent_on", "-created_at", "-id"]
        verbose_name = _("Expense")
        verbose_name_plural = _("Expenses")
        indexes = [models.Index(fields=["branch", "spent_on"])]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="expenses_amount_positive"),
            models.CheckConstraint(
                condition=Q(method__isnull=True) | Q(branch__isnull=False),
                name="expenses_cash_needs_branch",
            ),
            models.CheckConstraint(
                condition=(Q(kind="expense") & Q(reverses__isnull=True))
                | (Q(kind="reversal") & Q(reverses__isnull=False) & ~Q(reason="")),
                name="expenses_reversal_shape",
            ),
        ]

    def __str__(self):
        return f"{self.category_id}: {self.amount} {self.spent_on}"
