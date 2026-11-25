"""Purchase cost and margin by weighted average cost (owner's answer Q-S8). Pure."""

from collections.abc import Iterable
from fractions import Fraction


def unit_cost(receipts: Iterable[tuple[int, int | None]]) -> Fraction | None:
    """Weighted average cost of one unit from [(quantity, total cost or None)].

    None when there are no receipts or any receipt has no cost: a margin from part of the
    deliveries would look exact and be wrong."""
    qty = 0
    cost = 0
    for q, c in receipts:
        if c is None:
            return None
        qty += q
        cost += c
    if qty <= 0:
        return None
    return Fraction(cost, qty)


def cost_of_sold(sold_qty: int, unit: Fraction | None) -> Fraction | None:
    """What the sold units cost to buy, exact. The caller rounds it to whole so'm with
    billing's one rounding function (billing.services.round_amount)."""
    if unit is None:
        return None
    return unit * sold_qty


def margin(revenue: int, cost: int | None) -> int | None:
    return None if cost is None else revenue - cost
