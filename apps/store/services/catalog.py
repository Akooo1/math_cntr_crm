"""Catalog and prices: Direktor only (store.catalog.manage)."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.permissions import require_perm

from ..models import Price, Product


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


def create_product(
    *,
    actor,
    kind: str,
    name: str,
    price: int,
    effective_from: dt.date,
    low_stock_threshold: int = 0,
    sort_order: int = 100,
) -> Product:
    require_perm(actor, "store.catalog.manage")
    if kind not in Product.Kind.values:
        raise ValidationError(_("Choose the type."))
    name = (name or "").strip()
    if not name:
        raise ValidationError(_("Write the name."))
    try:
        with transaction.atomic():
            product = Product.objects.create(
                kind=kind,
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
    """Name, threshold, order, active. The type never changes once created."""
    require_perm(actor, "store.catalog.manage")
    allowed = {"name", "low_stock_threshold", "sort_order", "is_active"}
    if set(fields) - allowed:
        raise ValueError(f"not editable: {set(fields) - allowed}")
    if "name" in fields:
        fields["name"] = (fields["name"] or "").strip()
        if not fields["name"]:
            raise ValidationError(_("Write the name."))
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
