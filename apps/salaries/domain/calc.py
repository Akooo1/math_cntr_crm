"""Teacher salary math (docs/SPEC.md §13.1). Pure Python: no Django, no database.

Key = (student_id, group_id, payment_month): money a student paid in one month that FIFO
allocation applied to one group's charges.
"""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

Key = tuple[int, int, dt.date]

SHARE = "share"
CORRECTION = "correction"


@dataclass(frozen=True)
class RateRow:
    effective_from: dt.date
    order: tuple  # tie-break for rows with the same month: later created wins
    rate_bp: int


def rate_on(rows: list[RateRow], month: dt.date, default_bp: int) -> int:
    """The rate in force in `month`: the latest row starting on or before it."""
    best = None
    for row in rows:
        if row.effective_from <= month and (
            best is None or (row.effective_from, row.order) > (best.effective_from, best.order)
        ):
            best = row
    return default_bp if best is None else best.rate_bp


@dataclass(frozen=True)
class DraftLine:
    student_id: int
    group_id: int
    payment_month: dt.date
    teacher_id: int
    kind: str
    base: int
    rate_bp: int
    amount: int


def draft_lines(
    month: dt.date,
    live: dict[Key, int],
    accounted: dict[Key, int],
    teacher_of: dict[int, int],
    rate_for: Callable[[int, dt.date], int],
    share: Callable[[int, int], int],
) -> list[DraftLine]:
    """Lines for the open `month`: every key whose live money differs from what closed
    months already paid. `share(base, rate_bp)` rounds (billing's percent_of)."""
    lines = []
    for key in sorted(set(live) | set(accounted), key=lambda k: (k[2], k[1], k[0])):
        student_id, group_id, payment_month = key
        if payment_month > month:
            continue
        delta = live.get(key, 0) - accounted.get(key, 0)
        if delta == 0:
            continue
        teacher_id = teacher_of[group_id]
        rate_bp = rate_for(teacher_id, payment_month)
        lines.append(
            DraftLine(
                student_id=student_id,
                group_id=group_id,
                payment_month=payment_month,
                teacher_id=teacher_id,
                kind=SHARE if payment_month == month else CORRECTION,
                base=delta,
                rate_bp=rate_bp,
                amount=share(delta, rate_bp),
            )
        )
    return lines


@dataclass
class Totals:
    paid: int = 0  # money students paid this month (share lines' basis)
    share: int = 0
    corrections: int = 0
    fixed: int = 0  # fixed monthly salary (administrators, managers)
    bonuses: int = 0
    deductions: int = 0  # negative or zero (includes carry-over)

    @property
    def total(self) -> int:
        return self.share + self.corrections + self.fixed + self.bonuses + self.deductions


@dataclass(frozen=True)
class PayRow:
    effective_from: dt.date
    order: tuple  # tie-break for rows with the same month: later created wins
    amount: int


def fixed_on(rows: list[PayRow], month: dt.date) -> int:
    """The fixed monthly salary in force in `month` (0 = none)."""
    best = None
    for row in rows:
        if row.effective_from <= month and (
            best is None or (row.effective_from, row.order) > (best.effective_from, best.order)
        ):
            best = row
    return 0 if best is None else best.amount


def totals(lines: list, adjustments: list[tuple[str, int]], fixed: int = 0) -> Totals:
    """`lines` need .kind/.base/.amount; adjustments are (kind, signed amount)."""
    t = Totals(fixed=fixed)
    for line in lines:
        if line.kind == SHARE:
            t.paid += line.base
            t.share += line.amount
        else:
            t.corrections += line.amount
    for kind, amount in adjustments:
        if kind == "bonus":
            t.bonuses += amount
        else:
            t.deductions += amount
    return t
