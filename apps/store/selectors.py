"""Reads for the store. Every selector checks the permission and the branch scope."""

import datetime as dt
from dataclasses import dataclass

from django.db.models import F, Q, Sum
from django.http import Http404
from django.utils.translation import gettext as _

from apps.billing.models import ChargeNet
from apps.billing.services import round_amount
from apps.core import dates
from apps.core.permissions import (
    accessible_branch_ids,
    ensure_branch_access,
    has_perm,
    require_perm,
    scope_by_branch,
)
from apps.settings.models import Branch

from .domain import margin as margin_math
from .domain import stock as stock_math
from .models import Price, Product, Sale, SaleReversal, StockMovement


def branches_for(user):
    qs = Branch.objects.filter(is_active=True).order_by("name")
    ids = accessible_branch_ids(user)
    return qs if ids is None else qs.filter(pk__in=ids)


def pick_branch(user, raw=None, branch_filter=None) -> tuple[Branch | None, list[Branch]]:
    """The branch a store screen works on: `raw` (?filial=), else the top-bar switcher, else
    the user's only branch. None when the user has to choose (Direktor, several branches)."""
    branches = list(branches_for(user))
    wanted = raw or branch_filter
    if wanted:
        for b in branches:
            if str(b.pk) == str(wanted):
                return b, branches
        raise Http404
    return (branches[0] if len(branches) == 1 else None), branches


def current_prices(day: dt.date | None = None) -> dict[int, Price]:
    """{product_id: price in force on `day`} (latest effective_from, then latest created)."""
    day = day or dates.today()
    out: dict[int, Price] = {}
    rows = Price.objects.filter(effective_from__lte=day).order_by(
        "product_id", "-effective_from", "-created_at", "-id"
    )
    for p in rows:
        out.setdefault(p.product_id, p)
    return out


def on_hand_map(branch_id: int | None, *, until: dt.date | None = None) -> dict[int, int]:
    """{product_id: quantity} in one branch (or all branches when None), optionally as of a
    date. Always computed from the movements."""
    qs = StockMovement.objects.all()
    if branch_id is not None:
        qs = qs.filter(branch_id=branch_id)
    if until is not None:
        qs = qs.filter(movement_date__lte=until)
    return {
        r["product_id"]: int(r["q"] or 0)
        for r in qs.values("product_id").annotate(q=Sum("quantity"))
    }


@dataclass
class StockRow:
    product: Product
    price: Price | None
    on_hand: int
    low: bool


def stock_rows(user, branch: Branch, *, kind: str | None = None, active_only=False):
    require_perm(user, "store.view")
    ensure_branch_access(user, branch.pk)
    products = Product.objects.all()
    if kind:
        products = products.filter(kind=kind)
    if active_only:
        products = products.filter(is_active=True)
    prices = current_prices()
    stock = on_hand_map(branch.pk)
    return [
        StockRow(
            product=p,
            price=prices.get(p.pk),
            on_hand=stock.get(p.pk, 0),
            low=stock_math.is_low(stock.get(p.pk, 0), p.low_stock_threshold),
        )
        for p in products.order_by("kind", "sort_order", "name")
    ]


def sell_tiles(user, branch: Branch) -> list[StockRow]:
    """Active items with a price, for the sell screen."""
    require_perm(user, "store.sell")
    return [
        r
        for r in stock_rows(user, branch, kind=Product.Kind.ITEM, active_only=True)
        if r.price is not None
    ]


def books_for_giving(user, branch: Branch) -> list[StockRow]:
    require_perm(user, "store.sell")
    return [
        r
        for r in stock_rows(user, branch, kind=Product.Kind.BOOK, active_only=True)
        if r.price is not None
    ]


def get_product(user, pk) -> Product:
    require_perm(user, "store.view")
    product = Product.objects.filter(pk=pk).first()
    if product is None:
        raise Http404
    return product


def movements(user, product: Product, branch_id: int | None, limit=200):
    require_perm(user, "store.view")
    qs = scope_by_branch(StockMovement.objects.filter(product=product), user)
    if branch_id is not None:
        qs = qs.filter(branch_id=branch_id)
    return qs.select_related("branch", "created_by", "sale_line__sale__student")[:limit]


def sales_for(user, branch_filter=None):
    require_perm(user, "store.view")
    qs = scope_by_branch(Sale.objects.all(), user)
    if branch_filter is not None:
        qs = qs.filter(branch_id=branch_filter)
    return qs.select_related(
        "branch", "student", "method", "sold_by", "reversal", "reversal__created_by"
    ).prefetch_related("lines__product")


def sales_on(user, branch_id: int, day: dt.date):
    return sales_for(user, branch_id).filter(sold_on=day)


def get_sale(user, pk) -> Sale:
    sale = sales_for(user).filter(pk=pk).first()
    if sale is None:
        raise Http404
    return sale


def student_books(user, student) -> list[dict]:
    """Books given to a student, newest first, with whether a book on account is paid."""
    require_perm(user, "store.view")
    ensure_branch_access(user, student.branch_id)
    sales = list(
        Sale.objects.filter(student=student)
        .select_related("method", "reversal")
        .prefetch_related("lines__product")
        .order_by("-created_at", "-id")
    )
    nets = {
        c.charge_id: c
        for c in ChargeNet.objects.filter(charge_id__in=[s.charge_id for s in sales if s.charge_id])
    }
    out = []
    for s in sales:
        status = "paid"
        if s.charge_id:
            row = nets.get(s.charge_id)
            open_amount = (row.net - row.paid) if row else 0
            status = "open" if open_amount > 0 else "paid"
            if row and row.net == 0:
                status = "cancelled"
        if hasattr(s, "reversal"):
            status = "cancelled"
        out.append({"sale": s, "line": s.lines.all()[0], "status": status})
    return out


# --- Cash report source (billing's extension point, SPEC 17.4) ----------------------------


def _describe(sale: Sale) -> str:
    text = ", ".join(f"{line.product.name} × {line.quantity}" for line in sale.lines.all())
    if sale.student_id:
        text = f"{text} — {sale.student.full_name}"
    return text


def cash_lines(branch_id: int, day: dt.date) -> list:
    from django.urls import reverse

    from apps.billing.services.cash import CashLine

    lines = []
    paid = (
        Sale.objects.filter(branch_id=branch_id, settlement=Sale.Settlement.PAID)
        .select_related("student", "sold_by")
        .prefetch_related("lines__product")
    )
    for s in paid.filter(sold_on=day):
        lines.append(
            CashLine(
                source="store",
                method_id=s.method_id,
                direction="in",
                amount=s.total,
                at=s.created_at,
                by_name=s.sold_by.full_name,
                description=_describe(s),
                url=reverse("store:sale", args=[s.pk]),
            )
        )
    for r in SaleReversal.objects.filter(
        reversed_on=day, sale__in=paid.filter(branch_id=branch_id)
    ).select_related("created_by", "sale", "sale__student"):
        lines.append(
            CashLine(
                source="store",
                method_id=r.sale.method_id,
                direction="out",
                amount=r.sale.total,
                at=r.created_at,
                by_name=r.created_by.full_name,
                description=_describe(r.sale),
                kind_label=_("Cancelled"),
                url=reverse("store:sale", args=[r.sale_id]),
            )
        )
    return lines


def cash_active_days(since: dt.date, until: dt.date) -> set:
    sold = Sale.objects.filter(
        settlement=Sale.Settlement.PAID, sold_on__gte=since, sold_on__lte=until
    ).values_list("branch_id", "sold_on")
    reversed_ = SaleReversal.objects.filter(
        sale__settlement=Sale.Settlement.PAID, reversed_on__gte=since, reversed_on__lte=until
    ).values_list("sale__branch_id", "reversed_on")
    return set(sold) | set(reversed_)


# --- Report: Ombor va savdo (core.reports) --------------------------------------------------


def _report_branches(user, branch_id):
    ids = [b.pk for b in branches_for(user)]
    if branch_id is not None:
        ensure_branch_access(user, branch_id)
        ids = [i for i in ids if i == int(branch_id)]
    return ids


def stock_report(user, p):
    """Per product for the period and branch: received, sold, on hand at the end, sales
    amount (of which on account), and for the Direktor purchase cost and margin."""
    from apps.core.reports import Col, Result

    require_perm(user, "store.view")
    show_cost = has_perm(user, "store.cost.view")
    branch_ids = _report_branches(user, p.branch_id)
    mv = StockMovement.objects.filter(branch_id__in=branch_ids)
    in_period = mv.filter(movement_date__gte=p.date_from, movement_date__lte=p.date_to)

    def by_product(qs, value):
        return {
            r["product_id"]: int(r["v"] or 0) for r in qs.values("product_id").annotate(v=value)
        }

    received = by_product(in_period.filter(kind="receipt"), Sum("quantity"))
    sold_rows = in_period.filter(kind__in=["sale", "sale_reversal"])
    sold = {k: -v for k, v in by_product(sold_rows, Sum("quantity")).items()}
    money = F("quantity") * F("sale_line__unit_price")
    revenue = {k: -v for k, v in by_product(sold_rows, Sum(money)).items()}
    on_account = {
        k: -v
        for k, v in by_product(
            sold_rows.filter(sale_line__sale__settlement="on_account"), Sum(money)
        ).items()
    }
    closing = {
        r["product_id"]: int(r["v"] or 0)
        for r in mv.filter(movement_date__lte=p.date_to)
        .values("product_id")
        .annotate(v=Sum("quantity"))
    }
    # Current stock per branch that ever had the product (low-stock flag is about now).
    current: dict[int, list[int]] = {}
    for r in mv.values("branch_id", "product_id").annotate(v=Sum("quantity")):
        current.setdefault(r["product_id"], []).append(int(r["v"] or 0))

    # Weighted average cost per (branch, product) over receipts up to the period's end.
    receipts: dict[tuple[int, int], list] = {}
    for r in mv.filter(kind="receipt", movement_date__lte=p.date_to).values(
        "branch_id", "product_id", "quantity", "purchase_cost"
    ):
        receipts.setdefault((r["branch_id"], r["product_id"]), []).append(
            (r["quantity"], r["purchase_cost"])
        )
    sold_by_branch = {
        (r["branch_id"], r["product_id"]): -int(r["v"] or 0)
        for r in sold_rows.values("branch_id", "product_id").annotate(v=Sum("quantity"))
    }

    def cost_for(pid):
        """None ("—") as soon as a branch in scope has a delivery without a cost (Q-S8)."""
        total = 0
        for bid in branch_ids:
            qty = sold_by_branch.get((bid, pid), 0)
            got = receipts.get((bid, pid), [])
            if qty == 0 and not got:
                continue
            cost = margin_math.cost_of_sold(qty, margin_math.unit_cost(got))
            if cost is None:
                return None
            total += round_amount(cost)
        return total

    products = Product.objects.filter(
        Q(is_active=True) | Q(movements__branch_id__in=branch_ids)
    ).distinct()
    rows = []
    for prod in products.order_by("kind", "sort_order", "name"):
        low = any(stock_math.is_low(q, prod.low_stock_threshold) for q in current.get(prod.pk, [0]))
        row = [
            prod.name,
            prod.get_kind_display(),
            received.get(prod.pk, 0),
            sold.get(prod.pk, 0),
            closing.get(prod.pk, 0),
            revenue.get(prod.pk, 0),
            on_account.get(prod.pk, 0),
        ]
        if show_cost:
            cost = cost_for(prod.pk)
            row += [cost, margin_math.margin(revenue.get(prod.pk, 0), cost)]
        row.append(_("Yes") if low else "")
        rows.append(row)

    columns = [
        Col(_("Product")),
        Col(_("Type")),
        Col(_("Stock received"), "int"),
        Col(_("Sold"), "int"),
        Col(_("On hand"), "int"),
        Col(_("Sales amount"), "money"),
        Col(_("Of which pay later"), "money"),
    ]
    if show_cost:
        columns += [Col(_("Purchase cost"), "money"), Col(_("Margin"), "money")]
    columns.append(Col(_("Low stock")))

    def total(i):
        values = [r[i] for r in rows]
        return None if any(v is None for v in values) else sum(values)

    totals = [_("Total"), "", total(2), total(3), total(4), total(5), total(6)]
    if show_cost:
        totals += [total(7), total(8)]
    totals.append("")
    return Result(
        columns=columns,
        rows=rows,
        totals=totals,
        note=_(
            "Sold and sales amount are net of cancelled sales. On hand is at the end of the "
            "period. Purchase cost is the weighted average cost of the units sold; it is "
            "empty when a delivery was received without a cost."
        ),
    )


def low_stock(user, branch_filter=None, limit=8) -> list[dict]:
    """Active products that are low or out in a branch the user works in (dashboard)."""
    if not has_perm(user, "store.view"):
        return []
    branches = [b for b in branches_for(user) if branch_filter is None or b.pk == branch_filter]
    products = list(Product.objects.filter(is_active=True))
    out = []
    for b in branches:
        stock = on_hand_map(b.pk)
        for prod in products:
            if prod.pk not in stock:
                continue  # never stocked in this branch: not this branch's product
            q = stock.get(prod.pk, 0)
            if stock_math.is_low(q, prod.low_stock_threshold):
                out.append({"branch": b, "product": prod, "on_hand": q})
    out.sort(key=lambda r: (r["on_hand"], r["product"].name))
    return out[:limit]
