"""Pure date arithmetic (no Django imports), safe to use from domain/ packages."""

import calendar
import datetime as dt


def add_months(value: dt.date, months: int, day: int | None = None) -> dt.date:
    """Shift by whole months. The day is `day` (or value.day), clipped to the month's end."""
    index = value.year * 12 + (value.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, min(day or value.day, last))


def month_start(value: dt.date) -> dt.date:
    return value.replace(day=1)
