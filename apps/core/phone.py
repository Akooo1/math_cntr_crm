"""Uzbek phone numbers: stored as E.164 '+998XXXXXXXXX', displayed '+998 90 123 45 67'."""

import re

_DIGITS = re.compile(r"\D+")


class InvalidPhone(ValueError):
    pass


def normalize(raw: str | None) -> str:
    if raw is None:
        raise InvalidPhone("empty")
    digits = _DIGITS.sub("", str(raw))
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) != 12 or not digits.startswith("998"):
        raise InvalidPhone(raw)
    return "+" + digits


def normalize_or_none(raw: str | None) -> str | None:
    try:
        return normalize(raw)
    except InvalidPhone:
        return None


def format_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = _DIGITS.sub("", value)
    if len(digits) != 12:
        return value
    return f"+{digits[:3]} {digits[3:5]} {digits[5:8]} {digits[8:10]} {digits[10:12]}"
