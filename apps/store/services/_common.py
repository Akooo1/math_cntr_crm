import datetime as dt

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.core import dates

from ..models import Price, Product, StockMovement


def price_on(product: Product, day: dt.date) -> Price:
    price = (
        Price.objects.filter(product=product, effective_from__lte=day)
        .order_by("-effective_from", "-created_at", "-id")
        .first()
    )
    if price is None:
        raise ValidationError(
            _("%(product)s has no price yet. The director sets it in Settings.")
            % {"product": product.name}
        )
    return price


def lock_products(product_ids) -> dict[int, Product]:
    """Row-lock products in id order (no deadlocks), so two cashiers can't both sell the
    last unit. Stock is per branch, the lock is per product: fine at this size."""
    rows = Product.objects.select_for_update().filter(pk__in=sorted(set(product_ids)))
    return {p.pk: p for p in rows.order_by("pk")}


def on_hand(branch_id: int, product_ids) -> dict[int, int]:
    rows = (
        StockMovement.objects.filter(branch_id=branch_id, product_id__in=list(product_ids))
        .values("product_id")
        .annotate(q=Sum("quantity"))
    )
    out = {pk: 0 for pk in product_ids}
    out.update({r["product_id"]: int(r["q"] or 0) for r in rows})
    return out


def not_enough(product: Product, have: int, wanted: int) -> ValidationError:
    return ValidationError(
        _("Not enough %(product)s in stock: %(have)d left, %(wanted)d asked.")
        % {"product": product.name, "have": have, "wanted": wanted}
    )


def check_not_future(day: dt.date) -> None:
    if day > dates.today():
        raise ValidationError(_("The date can't be in the future."))
