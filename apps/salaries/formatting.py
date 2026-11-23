"""Percent text <-> basis points for rate inputs and display."""

import re


def parse_percent(raw: str) -> int:
    """ "50" or "62,5" -> basis points (5000, 6250). Two decimals at most."""
    raw = (raw or "").strip().replace(",", ".").rstrip("%").strip()
    if not re.fullmatch(r"\d{1,3}(\.\d{1,2})?", raw):
        raise ValueError(raw)
    whole, _sep, frac = raw.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def format_percent(bp: int) -> str:
    whole, frac = divmod(bp, 100)
    return str(whole) if not frac else f"{whole},{frac:02d}".rstrip("0")
