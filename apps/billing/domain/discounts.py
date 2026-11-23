"""Discount lines (docs/SPEC.md 6.4.4, Q-8). Pure functions.

Percents add up and apply to the base; fixed amounts come after. Each discount is its own
line, and the total never takes the net below zero.
"""

from dataclasses import dataclass
from fractions import Fraction

from .rounding import percent_of, round_amount


@dataclass(frozen=True)
class Rule:
    key: object  # whatever identifies the source (assignment id)
    kind: str  # "percent" | "fixed"
    value: int  # basis points or so'm


def lines(base: int, rules: list[Rule], step: int) -> list[tuple[object, int]]:
    """[(key, amount)] for every rule, in order: percents first, then fixed amounts."""
    out = []
    remaining = base
    ordered = [r for r in rules if r.kind == "percent"] + [r for r in rules if r.kind == "fixed"]
    for rule in ordered:
        amount = percent_of(base, rule.value, step) if rule.kind == "percent" else rule.value
        amount = max(0, min(amount, remaining))
        remaining -= amount
        out.append((rule.key, amount))
    return out


def net(base: int, rules: list[Rule], step: int) -> int:
    return base - sum(a for _k, a in lines(base, rules, step))


def spread(total: int, weights: list[int], step: int) -> list[int]:
    """Split `total` over parts proportionally to `weights` (rounded to `step`); the
    remainder goes to the first part. Used for a fixed discount on an installment course."""
    if not weights:
        return []
    whole = sum(weights)
    if whole <= 0:
        return [total] + [0] * (len(weights) - 1)
    rest = [round_amount(Fraction(total * w, whole), step) for w in weights[1:]]
    return [total - sum(rest), *rest]
