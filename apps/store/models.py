"""Books and counter sales (docs/SPEC.md 17). Stock on hand is never stored: it is the sum of
the append-only stock movements, like the balance is the sum of the ledger."""

from django.conf import settings as dj_settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from apps.billing.models import Charge, PaymentMethod
from apps.core.model_fields import MoneyField
from apps.settings.models import Branch


class Category(models.Model):
    """Mahsulot turi: a category the Direktor names (Kitoblar, Daftarlar, ...). "Like books"
    decides how its products behave: given to a group and paid later (books) or sold at
    the counter (items). SPEC §25."""

    name = models.CharField(_("Name"), max_length=100, unique=True)
    is_book = models.BooleanField(
        _("Like books"),
        default=False,
        help_text=_("Can be given to a whole group and paid later, like books."),
    )
    is_active = models.BooleanField(_("Active"), default=True)
    sort_order = models.PositiveIntegerField(_("Order"), default=100)

    class Meta:
        db_table = "store_category"
        ordering = ["sort_order", "name"]
        verbose_name = _("Product category")
        verbose_name_plural = _("Product categories")

    def __str__(self):
        return self.name


class Product(models.Model):
    """Catalog row (books and items alike). Global; stock is per branch. A product that was
    never received, sold or given can be deleted (SPEC §25); a used one only hidden."""

    class Kind(models.TextChoices):
        BOOK = "book", pgettext_lazy("product", "Book")
        ITEM = "item", _("Item")

    # Follows the category's "like books" (kept for the book / item rules in the services).
    kind = models.CharField(_("Type"), max_length=10, choices=Kind.choices)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        null=True,
        related_name="products",
        verbose_name=_("Category"),
    )
    name = models.CharField(_("Name"), max_length=150)
    low_stock_threshold = models.PositiveIntegerField(
        _("Low-stock threshold"),
        default=0,
        help_text=_("Warn when this many or fewer are left in a branch. 0 = no warning."),
    )
    is_active = models.BooleanField(_("Active"), default=True)
    sort_order = models.PositiveIntegerField(_("Order"), default=100)
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "store_product"
        ordering = ["kind", "sort_order", "name"]
        verbose_name = _("Product")
        verbose_name_plural = _("Products")
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "name"],
                name="uniq_store_product_name",
                violation_error_message=_("A product with this name already exists."),
            )
        ]

    def __str__(self):
        return self.name


class Price(models.Model):
    """Immutable. A price change is a new row; this table is the price history."""

    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="prices", verbose_name=_("Product")
    )
    amount = MoneyField(_("Price"))
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
        db_table = "store_price"
        ordering = ["-effective_from", "-created_at", "-id"]
        verbose_name = _("Price")
        verbose_name_plural = _("Prices")
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="store_price_positive")
        ]

    def __str__(self):
        return f"{self.product} {self.amount}"


class Sale(models.Model):
    """One basket (items) or one book handed to a student. Append-only."""

    class Settlement(models.TextChoices):
        PAID = "paid", _("Paid now")
        ON_ACCOUNT = "on_account", _("Pay later")

    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name="+", verbose_name=_("Branch")
    )
    student = models.ForeignKey(
        "students.Student",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Student"),
    )
    sold_on = models.DateField(_("Date"), db_index=True)
    settlement = models.CharField(_("Payment"), max_length=12, choices=Settlement.choices)
    method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Payment method"),
    )
    charge = models.OneToOneField(
        Charge,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Charge"),
    )
    total = MoneyField(_("Amount"))
    sold_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Sold by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "store_sale"
        ordering = ["-created_at", "-id"]
        verbose_name = _("Sale")
        verbose_name_plural = _("Sales")
        constraints = [
            models.CheckConstraint(condition=Q(total__gt=0), name="store_sale_total_positive"),
            models.CheckConstraint(
                condition=(
                    Q(settlement="paid", method__isnull=False, charge__isnull=True)
                    | Q(
                        settlement="on_account",
                        method__isnull=True,
                        charge__isnull=False,
                        student__isnull=False,
                    )
                ),
                name="store_sale_settlement_shape",
            ),
        ]

    def __str__(self):
        return f"#{self.pk} {self.sold_on}"


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="+", verbose_name=_("Product")
    )
    quantity = models.PositiveIntegerField(_("Quantity"))
    price = models.ForeignKey(Price, on_delete=models.PROTECT, related_name="+")
    unit_price = MoneyField(_("Price"))
    amount = MoneyField(_("Amount"))

    class Meta:
        db_table = "store_sale_line"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="store_line_qty_positive"),
            models.CheckConstraint(condition=Q(unit_price__gt=0), name="store_line_price_positive"),
            models.CheckConstraint(
                condition=Q(amount=F("unit_price") * F("quantity")), name="store_line_amount"
            ),
        ]

    def __str__(self):
        return f"{self.product} × {self.quantity}"


class SaleReversal(models.Model):
    """Bekor qilish: cancels a whole sale. Dated the day it is made. Direktor only."""

    sale = models.OneToOneField(Sale, on_delete=models.PROTECT, related_name="reversal")
    reversed_on = models.DateField(_("Date"))
    reason = models.TextField(_("Reason"))
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Reversed by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "store_sale_reversal"
        constraints = [
            models.CheckConstraint(condition=~Q(reason=""), name="store_reversal_needs_reason")
        ]

    def __str__(self):
        return f"#{self.sale_id}"


class StockMovement(models.Model):
    """Append-only. Stock on hand = Σ quantity per (branch, product)."""

    class Kind(models.TextChoices):
        RECEIPT = "receipt", _("Stock received")
        SALE = "sale", _("Sold")
        SALE_REVERSAL = "sale_reversal", _("Sale cancelled")
        CORRECTION = "correction", _("Stock correction")

    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name="+", verbose_name=_("Branch")
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="movements", verbose_name=_("Product")
    )
    kind = models.CharField(_("Type"), max_length=15, choices=Kind.choices)
    quantity = models.IntegerField(_("Quantity"))  # signed
    movement_date = models.DateField(_("Date"))
    purchase_cost = MoneyField(_("Purchase cost"), null=True, blank=True)
    sale_line = models.ForeignKey(
        SaleLine, on_delete=models.PROTECT, null=True, blank=True, related_name="movements"
    )
    reason = models.TextField(_("Reason"), blank=True)
    note = models.CharField(_("Note"), max_length=255, blank=True)
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Created by"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "store_stock_movement"
        ordering = ["-movement_date", "-created_at", "-id"]
        verbose_name = _("Stock movement")
        verbose_name_plural = _("Stock movements")
        indexes = [models.Index(fields=["branch", "product", "movement_date"], name="store_mv_bpd")]
        constraints = [
            models.CheckConstraint(condition=~Q(quantity=0), name="store_mv_qty_nonzero"),
            models.CheckConstraint(
                condition=~Q(kind="receipt") | Q(quantity__gt=0), name="store_mv_receipt_in"
            ),
            models.CheckConstraint(
                condition=~Q(kind="sale") | Q(quantity__lt=0, sale_line__isnull=False),
                name="store_mv_sale_out",
            ),
            models.CheckConstraint(
                condition=~Q(kind="sale_reversal") | Q(quantity__gt=0, sale_line__isnull=False),
                name="store_mv_reversal_in",
            ),
            models.CheckConstraint(
                condition=~Q(kind="correction") | ~Q(reason=""),
                name="store_mv_correction_reason",
            ),
            models.CheckConstraint(
                condition=Q(purchase_cost__isnull=True) | Q(kind="receipt", purchase_cost__gte=0),
                name="store_mv_cost_on_receipt",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity}"


class StockOnHand(models.Model):
    """`store_stock_on_hand` view (read-only)."""

    id = models.BigIntegerField(primary_key=True)  # min movement id of the group
    branch = models.ForeignKey(Branch, on_delete=models.DO_NOTHING, related_name="+")
    product = models.ForeignKey(Product, on_delete=models.DO_NOTHING, related_name="+")
    quantity = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = "store_stock_on_hand"

    def __str__(self):
        return f"{self.product_id}@{self.branch_id}: {self.quantity}"
