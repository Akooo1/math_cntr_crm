"""Catalog and prices: Direktor only (store.catalog.manage)."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.permissions import require_perm

from ..models import Category, Price, Product, SaleLine, StockMovement


def add_price(*, actor, product: Product, amount: int, effective_from: dt.date, note="") -> Price:
    """Prices are never edited. A new row from `effective_from`; sold lines keep theirs."""
    require_perm(actor, "store.catalog.manage")
    if amount is None or amount <= 0:
        raise ValidationError(_("The amount must be positive."))
    with transaction.atomic():
        price = Price.objects.create(
            product=product,
            amount=amount,
            effective_from=effective_from,
            note=(note or "").strip(),
            created_by=actor,
        )
        audit.record(actor, "store.price.create", price, after=audit.snapshot(price))
    return price


def _kind_of(category: Category) -> str:
    return Product.Kind.BOOK if category.is_book else Product.Kind.ITEM


def default_category(kind: str) -> Category:
    """The first active category that behaves like `kind` (book / item)."""
    category = (
        Category.objects.filter(is_book=kind == Product.Kind.BOOK, is_active=True)
        .order_by("sort_order", "name")
        .first()
    )
    if category is None:
        raise ValidationError(_("Create a product category first."))
    return category


def create_product(
    *,
    actor,
    name: str,
    price: int,
    effective_from: dt.date,
    kind: str | None = None,
    category: Category | None = None,
    low_stock_threshold: int = 0,
    sort_order: int = 100,
) -> Product:
    """A product in a category (or, without one, the first category of `kind`)."""
    require_perm(actor, "store.catalog.manage")
    if category is None:
        if kind not in Product.Kind.values:
            raise ValidationError(_("Choose the category."))
        category = default_category(kind)
    if not category.is_active:
        raise ValidationError(_("Choose the category."))
    name = (name or "").strip()
    if not name:
        raise ValidationError(_("Write the name."))
    try:
        with transaction.atomic():
            product = Product.objects.create(
                kind=_kind_of(category),
                category=category,
                name=name,
                low_stock_threshold=low_stock_threshold,
                sort_order=sort_order,
                created_by=actor,
            )
            audit.record(actor, "store.product.create", product, after=audit.snapshot(product))
            add_price(actor=actor, product=product, amount=price, effective_from=effective_from)
    except IntegrityError as exc:
        raise ValidationError(_("A product with this name already exists.")) from exc
    return product


def update_product(*, actor, product: Product, **fields) -> Product:
    """Name, category, threshold, order, active. A product moves only to a category that
    behaves the same (like books or not): books already given stay books."""
    require_perm(actor, "store.catalog.manage")
    allowed = {"name", "category", "low_stock_threshold", "sort_order", "is_active"}
    if set(fields) - allowed:
        raise ValueError(f"not editable: {set(fields) - allowed}")
    if "name" in fields:
        fields["name"] = (fields["name"] or "").strip()
        if not fields["name"]:
            raise ValidationError(_("Write the name."))
    if "category" in fields and _kind_of(fields["category"]) != product.kind:
        raise ValidationError(
            _("Move it to a category that is also %(kind)s.")
            % {
                "kind": _("like books")
                if product.kind == Product.Kind.BOOK
                else _("not like books")
            }
        )
    try:
        with transaction.atomic():
            obj = Product.objects.select_for_update().get(pk=product.pk)
            before = audit.snapshot(obj)
            for k, v in fields.items():
                setattr(obj, k, v)
            obj.save(update_fields=list(fields))
            audit.record(
                actor, "store.product.update", obj, before=before, after=audit.snapshot(obj)
            )
    except IntegrityError as exc:
        raise ValidationError(_("A product with this name already exists.")) from exc
    return obj


def is_used(product: Product) -> bool:
    """Received, sold or given at least once: then it is part of past Kassa and Ombor days."""
    return (
        StockMovement.objects.filter(product=product).exists()
        or SaleLine.objects.filter(product=product).exists()
    )


def delete_product(*, actor, product: Product) -> None:
    """Delete a product added by mistake, with its prices (SPEC §25). Only one that was never
    received, sold or given: a used one is hidden instead, so past days stay correct."""
    require_perm(actor, "store.catalog.manage")
    with transaction.atomic():
        obj = Product.objects.select_for_update().get(pk=product.pk)
        if is_used(obj):
            raise ValidationError(
                _(
                    "This product was already received, sold or given, so it can't be deleted. "
                    "Deactivate it instead."
                )
            )
        audit.record(actor, "store.product.delete", obj, before=audit.snapshot(obj))
        Price.objects.filter(product=obj).delete()
        obj.delete()


def save_category(*, actor, form) -> Category:
    """Create or rename a category. "Like books" changes only while it has no products."""
    from apps.core import crud

    require_perm(actor, "store.catalog.manage")
    instance = form.instance
    if instance.pk:
        old = Category.objects.get(pk=instance.pk)
        if old.is_book != form.cleaned_data["is_book"] and old.products.exists():
            raise ValidationError(
                _(
                    'This category has products, so "like books" can\'t change. Create a new '
                    "category instead."
                )
            )
    return crud.save_form(form, actor=actor, action_prefix="store.category")


def delete_category(*, actor, category: Category) -> None:
    require_perm(actor, "store.catalog.manage")
    with transaction.atomic():
        obj = Category.objects.select_for_update().get(pk=category.pk)
        if obj.products.exists():
            raise ValidationError(_("Move or delete its products first."))
        audit.record(actor, "store.category.delete", obj, before=audit.snapshot(obj))
        obj.delete()
