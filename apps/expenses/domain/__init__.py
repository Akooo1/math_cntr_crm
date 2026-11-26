"""Branch profit math (docs/SPEC.md §20). Pure Python: no Django, no database."""

from collections.abc import Callable
from fractions import Fraction


def split(amount: int, weights: dict, round_fn: Callable[[Fraction], int]) -> dict:
    """Divide `amount` between the keys of `weights` in proportion to them; the parts add
    up to exactly `amount` (the rounding difference goes to the largest weight). All
    weights zero or negative -> equal parts. `round_fn` is billing's round_amount."""
    keys = list(weights)
    if not keys:
        return {}
    usable = {k: max(int(weights[k]), 0) for k in keys}
    total = sum(usable.values())
    if total <= 0:
        usable = {k: 1 for k in keys}
        total = len(keys)
    parts = {k: round_fn(Fraction(amount * usable[k], total)) for k in keys}
    biggest = max(keys, key=lambda k: (usable[k], -keys.index(k)))
    parts[biggest] += amount - sum(parts.values())
    return parts
