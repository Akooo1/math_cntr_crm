"""List pages: the header count ("248", or "25 / 248" when filtered), the money sum of the
shown rows, pagination and sortable columns. Every list view uses these, so every list
reads the same way (base.html renders `totals`; components/pagination.html renders
"1–25 / 248"; components/sort_th.html renders a sortable column header).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from django.core.paginator import Page, Paginator
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

PER_PAGE = 25
SORT_PARAM = "tartib"


@dataclass(frozen=True)
class Totals:
    """`total`: everything the user may see here (role and branch scope, the branch
    switcher). `shown`: what the page's filters leave. `amount`: on money lists, the sum of
    the shown rows (all pages, not just this one)."""

    total: int
    shown: int
    filtered: bool = False
    amount: int | None = None
    amount_label: str = field(default_factory=lambda: str(_("Total")))


def _count(rows) -> int:
    return rows.count() if isinstance(rows, QuerySet) else len(rows)


def totals(
    everything: QuerySet | list | int,
    shown: QuerySet | list | int | None = None,
    *,
    filtered: bool | None = None,
    amount: int | None = None,
    amount_label=None,
) -> Totals:
    """Totals for a list header. Pass the unfiltered rows and the filtered rows (querysets,
    lists or counts). `filtered` defaults to "a filtered set was given"."""
    total = everything if isinstance(everything, int) else _count(everything)
    if shown is None:
        count, is_filtered = total, False
    else:
        count = shown if isinstance(shown, int) else _count(shown)
        is_filtered = True if filtered is None else filtered
    kwargs = {"amount_label": str(amount_label)} if amount_label else {}
    return Totals(total=total, shown=count, filtered=is_filtered, amount=amount, **kwargs)


def active_filters(request, names: Iterable[str]) -> bool:
    """True when any of these GET parameters is set to a non-empty value."""
    return any((request.GET.get(n) or "").strip() for n in names)


def paginate(request, rows, per_page: int = PER_PAGE) -> tuple[Page, str]:
    """The current page and the query string of the other GET parameters (for links)."""
    page = Paginator(rows, per_page).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return page, query.urlencode()


@dataclass(frozen=True)
class Sort:
    key: str
    desc: bool
    url: dict  # column key -> query string that sorts by it (toggling the direction)


def _sort_state(request, keys: Iterable[str], default: str) -> Sort:
    raw = (request.GET.get(SORT_PARAM) or default).strip()
    desc = raw.startswith("-")
    key = raw.lstrip("-")
    if key not in keys:
        desc = default.startswith("-")
        key = default.lstrip("-")
    urls = {}
    for k in keys:
        query = request.GET.copy()
        query.pop("page", None)
        query[SORT_PARAM] = k if (k != key or desc) else f"-{k}"
        urls[k] = query.urlencode()
    return Sort(key=key, desc=desc, url=urls)


def sort_queryset(
    request, qs: QuerySet, columns: dict[str, tuple[str, ...]], default: str
) -> tuple[QuerySet, Sort]:
    """Order `qs` by `?tartib=<key>` or `?tartib=-<key>`. `columns` maps a key to the model
    fields to order by (ascending). Unknown keys fall back to `default`."""
    state = _sort_state(request, columns, default)
    order = []
    for f in columns[state.key]:
        flip = f.startswith("-") != state.desc
        order.append(("-" if flip else "") + f.lstrip("-"))
    return qs.order_by(*order), state


def sort_rows(request, rows: list, columns: dict[str, Callable], default: str) -> tuple[list, Sort]:
    """The same for rows computed in Python: `columns` maps a key to a sort-key function."""
    state = _sort_state(request, columns, default)
    return sorted(rows, key=columns[state.key], reverse=state.desc), state
