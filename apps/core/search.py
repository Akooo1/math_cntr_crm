"""Apostrophe-insensitive text search (CLAUDE.md: ' ‘ ’ ʻ ʼ are equal in search)."""

from django.db.models import F, Func, Q, QuerySet, Value

from .text import APOSTROPHES, normalize_apostrophes


def normalized(field: str) -> Func:
    return Func(F(field), Value(APOSTROPHES), Value("'" * len(APOSTROPHES)), function="translate")


def text_search(qs: QuerySet, query: str, fields: list[str], digit_fields: list[str] = ()):
    """Filter `qs` where any text field contains `query` (case- and apostrophe-insensitive)
    or any digit field contains the digits of `query` (at least 3)."""
    query = " ".join(normalize_apostrophes(query or "").split())
    if not query:
        return qs
    cond = Q()
    for f in fields:
        alias = f"_s_{f}"
        qs = qs.annotate(**{alias: normalized(f)})
        cond |= Q(**{f"{alias}__icontains": query})
    digits = "".join(c for c in query if c.isdigit())
    if len(digits) >= 3:
        for f in digit_fields:
            cond |= Q(**{f"{f}__contains": digits})
    return qs.filter(cond)
