"""Kirim (stock received) and corrections. Stock on hand is never stored."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit, dates
from apps.core.permissions import ensure_branch_access, require_perm
from apps.settings.models import Branch

from ..domain import stock as stock_math
from ..models import Product, StockMovement
from ._common import check_not_future, lock_products, on_hand


def receive_stock(
    *,
    actor,
    branch: Branch,
    product: Product,
    quantity: int,
    received_on: dt.date,
    purchase_cost: int | None = None,
    note: str = "",
) -> StockMovement:
    """Admins record Kirim for their own branch, the Direktor for any (owner's Q-S2)."""
    require_perm(actor, "store.stock.receive")
    ensure_branch_access(actor, branch.pk)
    if quantity is None or quantity <= 0:
        raise ValidationError(_("The quantity must be at least 1."))
    if purchase_cost is not None and purchase_cost < 0:
        raise ValidationError(_("The amount can't be negative."))
    check_not_future(received_on)
    with transaction.atomic():
        row = StockMovement.objects.create(
            branch=branch,
            product=product,
            kind=StockMovement.Kind.RECEIPT,
            quantity=quantity,
            movement_date=received_on,
            purchase_cost=purchase_cost,
            note=(note or "").strip(),
            created_by=actor,
        )
        audit.record(
            actor, "store.stock.receive", row, after=audit.snapshot(row), branch_id=branch.pk
        )
    return row


def correct_stock(
    *, actor, branch: Branch, product: Product, counted: int, reason: str
) -> StockMovement:
    """Bring the stock in line with a physical count. Direktor only, with a reason."""
    require_perm(actor, "store.stock.correct")
    ensure_branch_access(actor, branch.pk)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError(_("Write the reason."))
    if counted is None or counted < 0:
        raise ValidationError(_("The quantity can't be negative."))
    with transaction.atomic():
        lock_products([product.pk])
        current = on_hand(branch.pk, [product.pk])[product.pk]
        delta = stock_math.correction_delta(current, counted)
        if delta == 0:
            raise ValidationError(_("The count matches the stock. Nothing to correct."))
        row = StockMovement.objects.create(
            branch=branch,
            product=product,
            kind=StockMovement.Kind.CORRECTION,
            quantity=delta,
            movement_date=dates.today(),
            reason=reason,
            created_by=actor,
        )
        audit.record(
            actor,
            "store.stock.correct",
            row,
            before={"on_hand": current},
            after={**audit.snapshot(row), "on_hand": counted},
            reason=reason,
            branch_id=branch.pk,
            only_changes=False,
        )
    return row
