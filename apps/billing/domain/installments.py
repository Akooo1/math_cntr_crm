"""Installment schedule builder (docs/SPEC.md 6.4.3). Pure functions, no Django."""

import datetime as dt
from dataclasses import dataclass
from fractions import Fraction

from apps.core.datemath import add_months

from .rounding import BP, floor_to_step, round_amount


@dataclass(frozen=True)
class Part:
    part_no: int
    amount: int
    due_date: dt.date


@dataclass(frozen=True)
class TemplateRule:
    parts_count: int
    split_mode: str  # "equal" | "custom"
    first_due: str  # "on_start" | "fixed_day"
    interval_months: int = 1
    due_day_of_month: int | None = None
    shares_bp: tuple[int, ...] = ()


class InvalidTemplate(ValueError):
    pass


def validate_rule(rule: TemplateRule) -> None:
    if rule.parts_count < 2:
        raise InvalidTemplate("parts_count")
    if rule.interval_months < 1:
        raise InvalidTemplate("interval_months")
    if rule.first_due == "fixed_day" and not rule.due_day_of_month:
        raise InvalidTemplate("due_day_of_month")
    if rule.due_day_of_month is not None and not 1 <= rule.due_day_of_month <= 28:
        raise InvalidTemplate("due_day_of_month")
    if rule.split_mode == "custom":
        if len(rule.shares_bp) != rule.parts_count:
            raise InvalidTemplate("shares_count")
        if sum(rule.shares_bp) != BP or any(s <= 0 for s in rule.shares_bp):
            raise InvalidTemplate("shares_sum")


def due_dates(rule: TemplateRule, start: dt.date) -> list[dt.date]:
    day = rule.due_day_of_month
    if rule.first_due == "fixed_day":
        first = start.replace(day=day) if start.day <= day else add_months(start, 1, day=day)
    else:
        first = start
    result = [first]
    for k in range(1, rule.parts_count):
        anchor = first if rule.first_due == "fixed_day" else start
        result.append(add_months(anchor, k * rule.interval_months, day=day))
    return result


def split_amounts(rule: TemplateRule, total: int, step: int) -> list[int]:
    """Parts 2..n are rounded to the step; the remainder goes to part 1 (SPEC Q-9)."""
    n = rule.parts_count
    if rule.split_mode == "custom":
        rest = [round_amount(Fraction(total * bp, BP), step) for bp in rule.shares_bp[1:]]
    else:
        rest = [floor_to_step(Fraction(total, n), step)] * (n - 1)
    first = total - sum(rest)
    if first < 0:
        raise InvalidTemplate("negative_first_part")
    return [first, *rest]


def build_schedule(rule: TemplateRule, total: int, start: dt.date, step: int) -> list[Part]:
    validate_rule(rule)
    if total < 0:
        raise ValueError("total must be >= 0")
    amounts = split_amounts(rule, total, step)
    return [
        Part(part_no=i + 1, amount=a, due_date=d)
        for i, (a, d) in enumerate(zip(amounts, due_dates(rule, start), strict=True))
    ]
