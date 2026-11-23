"""Director / branch admin dashboard numbers and the 6-month chart."""

import datetime as dt

from django.utils.translation import gettext as _

from apps.core import dates
from apps.core.datemath import add_months, month_start
from apps.core.permissions import apply_branch_filter, scope_by_branch
from apps.crm.models import Lead

from . import queries


def _nice_max(value: int) -> int:
    """A round axis top above `value`: 1, 2 or 5 × 10^k (so'm)."""
    if value <= 0:
        return 1_000_000
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 2, 5, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def _compact(value: int) -> str:
    """Axis label: 2 500 000 -> "2,5 mln", 400 000 -> "400 ming"."""
    if value >= 1_000_000:
        n = value / 1_000_000
        number = f"{n:.0f}" if n == int(n) else f"{n:.1f}".replace(".", ",")
        return _("%(n)s M") % {"n": number}
    if value >= 1000:
        return _("%(n)s K") % {"n": value // 1000}
    return str(value)


def overview(user, branch_id) -> dict:
    today = dates.today()
    this_month = month_start(today)
    last_month = add_months(this_month, -1)
    first = add_months(this_month, -5)
    months = queries.by_month(user, branch_id, first, today)
    collected_now = months[-1]["collected"]
    collected_prev = months[-2]["collected"] if len(months) > 1 else 0
    # Same days of last month, so the comparison is fair mid-month.
    prev_same = queries.collected_total(
        queries.payments(
            user,
            branch_id,
            last_month,
            min(add_months(today, -1), this_month - dt.timedelta(days=1)),
        )
    )
    open_, overdue = queries.debt(user, branch_id)
    leads = apply_branch_filter(scope_by_branch(Lead.objects.all(), user), branch_id).filter(
        created_at__date__gte=this_month
    )
    new_leads = leads.count()
    converted = leads.filter(student__isnull=False).count()
    top = _nice_max(max([m["charged"] for m in months] + [m["collected"] for m in months] + [0]))
    ticks = [top * i // 4 for i in range(5)]
    chart = {
        "months": [
            {
                **m,
                "charged_pct": round(100 * m["charged"] / top, 2),
                "collected_pct": round(100 * m["collected"] / top, 2),
            }
            for m in months
        ],
        "ticks": [{"value": t, "label": _compact(t), "pct": 100 * t / top} for t in ticks],
    }
    return {
        "collected_now": collected_now,
        "collected_prev": collected_prev,
        "collected_prev_same": prev_same,
        "charged_now": months[-1]["charged"],
        "open": open_,
        "overdue": overdue,
        "new_leads": new_leads,
        "converted": converted,
        "chart": chart,
        "branches": queries.by_branch(user, branch_id, this_month, today)
        if branch_id is None
        else [],
    }
