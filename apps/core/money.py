"""Money is whole so'm stored as int. Never float or Decimal for stored amounts."""

import re

from django.utils.translation import pgettext

NARROW_NBSP = " "


def group_digits(amount: int) -> str:
    sign = "-" if amount < 0 else ""
    digits = f"{abs(int(amount)):,}".replace(",", NARROW_NBSP)
    return sign + digits


def format_som(amount: int | None) -> str:
    """1250000 -> '1 250 000 so'm' (narrow no-break spaces)."""
    if amount is None:
        return ""
    unit = pgettext("currency", "sum")
    return f"{group_digits(amount)}{NARROW_NBSP}{unit}"


_NON_DIGITS = re.compile(r"[\s  ,._']")


def parse_amount(raw: str | int | None) -> int:
    """Parse user input like '1 250 000' into an int. Raises ValueError on anything else."""
    if raw is None:
        raise ValueError("empty")
    if isinstance(raw, int):
        return raw
    text = _NON_DIGITS.sub("", str(raw).strip())
    text = text.removesuffix("so'm").removesuffix("som")
    if not text or not re.fullmatch(r"-?\d+", text):
        raise ValueError(raw)
    return int(text)
