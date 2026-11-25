"""Stock arithmetic. Pure: no Django, no database."""

from collections.abc import Iterable


class NotEnoughStock(Exception):
    def __init__(self, product_key, on_hand: int, wanted: int):
        super().__init__(f"{product_key}: {on_hand} < {wanted}")
        self.product_key = product_key
        self.on_hand = on_hand
        self.wanted = wanted


def on_hand(quantities: Iterable[int]) -> int:
    """Signed movements (receipts and reversals +, sales -, corrections ±) summed."""
    return sum(quantities)


def merge_lines(lines: Iterable[tuple[object, int]]) -> dict:
    """[(product, qty)] -> {product: total qty}; quantities must be positive."""
    out: dict = {}
    for key, qty in lines:
        if qty <= 0:
            raise ValueError("quantity must be positive")
        out[key] = out.get(key, 0) + qty
    return out


def check_available(wanted: dict, available: dict) -> None:
    """Raise NotEnoughStock for the first product whose branch stock is below the request."""
    for key, qty in wanted.items():
        have = available.get(key, 0)
        if have < qty:
            raise NotEnoughStock(key, have, qty)


def correction_delta(current: int, counted: int) -> int:
    """The movement that brings the books in line with a physical count."""
    if counted < 0:
        raise ValueError("counted stock can't be negative")
    return counted - current


def is_low(quantity: int, threshold: int) -> bool:
    """Threshold 0 means no warning; an empty shelf is always flagged."""
    return quantity <= 0 or (threshold > 0 and quantity <= threshold)
