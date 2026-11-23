"""Lesson-based proration (docs/SPEC.md 6.4.2). Pure functions."""

import datetime as dt
from collections.abc import Iterable
from fractions import Fraction

from .rounding import round_amount


def billable_lessons(
    lesson_dates: Iterable[dt.date],
    window: tuple[dt.date, dt.date | None],
    freezes: Iterable[tuple[dt.date, dt.date | None]] = (),
) -> int:
    """Lessons inside the enrollment window [start, end) and outside every freeze [from, to)."""
    start, end = window
    freezes = list(freezes)

    def inside(day, a, b):
        return a <= day and (b is None or day < b)

    return sum(
        1
        for day in lesson_dates
        if inside(day, start, end) and not any(inside(day, f, t) for f, t in freezes)
    )


def prorate(base: int, billable: int, total: int, step: int) -> int:
    """base × billable / total, rounded half-up to `step`. Full price when nothing is missed;
    0 when the month has no lessons."""
    if total <= 0 or billable <= 0:
        return 0
    if billable >= total:
        return base
    return round_amount(Fraction(base * billable, total), step)
