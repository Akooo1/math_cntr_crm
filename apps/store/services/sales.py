"""Counter sales, books for students, reversals (docs/SPEC.md 17.3)."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import IntegrityError, InternalError, transaction
from django.utils.translation import gettext as _

from apps.billing import selectors as billing_selectors
from apps.billing import services as billing
from apps.billing.models import Charge, PaymentMethod
from apps.core import audit, dates, events
from apps.core.permissions import ensure_branch_access, require_perm
from apps.core.system_settings import get_setting
from apps.settings.models import Branch
from apps.students.models import Enrollment, Group, Student

from ..domain import stock as stock_math
from ..events import SaleRecorded, SaleReversed
from ..models import Product, Sale, SaleLine, SaleReversal, StockMovement
from ._common import lock_products, not_enough, on_hand, price_on


def _check_method(method: PaymentMethod) -> None:
    if not billing_selectors.cash_methods_for_entry().filter(pk=method.pk).exists():
        raise ValidationError(_("This payment method can't be used here."))


def _check_open_day(branch_id: int, day: dt.date) -> None:
    """Take the cash-day lock (shared with billing), then refuse a closed day."""
    billing.cash.lock_day(branch_id, day)
    if billing_selectors.is_day_closed(branch_id, day):
        raise ValidationError(
            _("The cash day %(day)s is closed.") % {"day": dates.format_date(day)}
        )


def _insert(model, **fields):
    """Insert, turning the database's closed-day trigger into a readable error."""
    try:
        with transaction.atomic():
            return model.objects.create(**fields)
    except (InternalError, IntegrityError) as exc:
        if "closed" in str(exc):
            raise ValidationError(_("The cash day is closed.")) from exc
        raise


def _take_stock(branch_id: int, wanted: dict[int, int], products: dict[int, Product]) -> None:
    available = on_hand(branch_id, wanted)
    try:
        stock_math.check_available(wanted, available)
    except stock_math.NotEnoughStock as exc:
        raise not_enough(products[exc.product_key], exc.on_hand, exc.wanted) from exc


def _write_sale(
    *,
    actor,
    branch_id: int,
    day: dt.date,
    wanted: dict[int, int],
    products: dict[int, Product],
    settlement: str,
    method=None,
    student=None,
    charge=None,
    prices=None,
) -> Sale:
    prices = prices or {pk: price_on(products[pk], day) for pk in wanted}
    total = sum(prices[pk].amount * qty for pk, qty in wanted.items())
    sale = _insert(
        Sale,
        branch_id=branch_id,
        student=student,
        sold_on=day,
        settlement=settlement,
        method=method,
        charge=charge,
        total=total,
        sold_by=actor,
    )
    for pk, qty in wanted.items():
        price = prices[pk]
        line = SaleLine.objects.create(
            sale=sale,
            product_id=pk,
            quantity=qty,
            price=price,
            unit_price=price.amount,
            amount=price.amount * qty,
        )
        StockMovement.objects.create(
            branch_id=branch_id,
            product_id=pk,
            kind=StockMovement.Kind.SALE,
            quantity=-qty,
            movement_date=day,
            sale_line=line,
            created_by=actor,
        )
    return sale


def _sale_snapshot(sale: Sale) -> dict:
    return {
        **audit.snapshot(sale),
        "lines": [
            {"product": line.product.name, "quantity": line.quantity, "amount": line.amount}
            for line in sale.lines.select_related("product")
        ],
    }


def sell_items(
    *, actor, branch: Branch, lines: list[tuple[Product, int]], method: PaymentMethod
) -> Sale:
    """One basket from the sell screen: items only, no student, paid now, dated today."""
    require_perm(actor, "store.sell")
    ensure_branch_access(actor, branch.pk)
    if not lines:
        raise ValidationError(_("Add at least one item."))
    try:
        wanted = stock_math.merge_lines((p.pk, q) for p, q in lines)
    except ValueError as exc:
        raise ValidationError(_("The quantity must be at least 1.")) from exc
    _check_method(method)
    today = dates.today()
    with transaction.atomic():
        _check_open_day(branch.pk, today)
        products = lock_products(wanted)
        for pk in wanted:
            p = products.get(pk)
            if p is None or p.kind != Product.Kind.ITEM or not p.is_active:
                raise ValidationError(_("Only active items can be sold here."))
        _take_stock(branch.pk, wanted, products)
        sale = _write_sale(
            actor=actor,
            branch_id=branch.pk,
            day=today,
            wanted=wanted,
            products=products,
            settlement=Sale.Settlement.PAID,
            method=method,
        )
        audit.record(
            actor, "store.sale.create", sale, after=_sale_snapshot(sale), branch_id=branch.pk
        )
        events.publish(SaleRecorded(sale_id=sale.pk, branch_id=branch.pk, total=sale.total))
    return sale


def _book_description(product: Product, qty: int) -> str:
    return _("Book: %(name)s × %(qty)d") % {"name": product.name, "qty": qty}


def _give_on_account(*, actor, student: Student, product: Product, qty: int, day, price) -> Sale:
    total = price.amount * qty
    charge = billing.ledger.create_charge(
        actor=actor,
        student_id=student.pk,
        branch_id=student.branch_id,
        kind=Charge.Kind.MANUAL,
        due_date=day + dt.timedelta(days=get_setting("store.book_due_days")),
        base_amount=total,
        amount=total,
        suggested_amount=None,
        description=_book_description(product, qty),
        discount_lines=[],
    )
    return _write_sale(
        actor=actor,
        branch_id=student.branch_id,
        day=day,
        wanted={product.pk: qty},
        products={product.pk: product},
        settlement=Sale.Settlement.ON_ACCOUNT,
        student=student,
        charge=charge,
        prices={product.pk: price},
    )


def _check_book(product: Product) -> None:
    if product is None or product.kind != Product.Kind.BOOK or not product.is_active:
        raise ValidationError(_("Choose an active book."))


def give_book(
    *,
    actor,
    student: Student,
    product: Product,
    quantity: int = 1,
    method: PaymentMethod | None = None,
) -> Sale:
    """Kitob berish from the student card. With `method`: paid now (a counter sale with the
    student attached; Kassa in, ledger untouched). Without: a charge due in N days."""
    require_perm(actor, "store.sell")
    ensure_branch_access(actor, student.branch_id)
    if quantity is None or quantity <= 0:
        raise ValidationError(_("The quantity must be at least 1."))
    if method is not None:
        _check_method(method)
    today = dates.today()
    with transaction.atomic():
        if method is not None:
            _check_open_day(student.branch_id, today)
        products = lock_products([product.pk])
        product = products.get(product.pk)
        _check_book(product)
        _take_stock(student.branch_id, {product.pk: quantity}, products)
        price = price_on(product, today)
        if method is None:
            sale = _give_on_account(
                actor=actor, student=student, product=product, qty=quantity, day=today, price=price
            )
        else:
            sale = _write_sale(
                actor=actor,
                branch_id=student.branch_id,
                day=today,
                wanted={product.pk: quantity},
                products=products,
                settlement=Sale.Settlement.PAID,
                method=method,
                student=student,
                prices={product.pk: price},
            )
        audit.record(
            actor, "store.book.give", sale, after=_sale_snapshot(sale), branch_id=sale.branch_id
        )
        events.publish(SaleRecorded(sale_id=sale.pk, branch_id=sale.branch_id, total=sale.total))
    return sale


def give_books_to_group(
    *, actor, group: Group, product: Product, student_ids: list[int]
) -> list[Sale]:
    """Guruhga kitob berish: one book and one charge (pay later) per ticked student of the
    group. Stock is checked for all of them first: either everyone gets one, or nobody."""
    require_perm(actor, "store.sell")
    ensure_branch_access(actor, group.branch_id)
    ids = sorted(set(student_ids or []))
    if not ids:
        raise ValidationError(_("Tick at least one student."))
    enrolled = set(
        Enrollment.objects.filter(
            group=group, student_id__in=ids, status__in=Enrollment.OPEN
        ).values_list("student_id", flat=True)
    )
    if enrolled != set(ids):
        raise ValidationError(_("Only students of this group can be chosen."))
    students = list(Student.objects.filter(pk__in=ids).order_by("pk"))
    today = dates.today()
    with transaction.atomic():
        products = lock_products([product.pk])
        product = products.get(product.pk)
        _check_book(product)
        _take_stock(group.branch_id, {product.pk: len(students)}, products)
        price = price_on(product, today)
        sales = []
        for student in students:
            sale = _give_on_account(
                actor=actor, student=student, product=product, qty=1, day=today, price=price
            )
            audit.record(
                actor,
                "store.book.give",
                sale,
                after={**_sale_snapshot(sale), "group": group.pk},
                branch_id=sale.branch_id,
            )
            sales.append(sale)
        for sale in sales:
            events.publish(
                SaleRecorded(sale_id=sale.pk, branch_id=sale.branch_id, total=sale.total)
            )
    return sales


def reverse_sale(*, actor, sale: Sale, reason: str) -> SaleReversal:
    """Bekor qilish: the whole sale, dated today, Direktor only. Stock comes back; a paid sale
    is money out in today's Kassa; a book on account gets its charge cancelled."""
    require_perm(actor, "store.sale.reverse")
    ensure_branch_access(actor, sale.branch_id)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError(_("Write the reason."))
    today = dates.today()
    with transaction.atomic():
        sale = Sale.objects.select_for_update().get(pk=sale.pk)
        if SaleReversal.objects.filter(sale=sale).exists():
            raise ValidationError(_("This sale is already cancelled."))
        if sale.settlement == Sale.Settlement.PAID:
            _check_open_day(sale.branch_id, today)
        reversal = _insert(
            SaleReversal, sale=sale, reversed_on=today, reason=reason, created_by=actor
        )
        for line in sale.lines.all():
            StockMovement.objects.create(
                branch_id=sale.branch_id,
                product_id=line.product_id,
                kind=StockMovement.Kind.SALE_REVERSAL,
                quantity=line.quantity,
                movement_date=today,
                sale_line=line,
                created_by=actor,
            )
        if sale.charge_id:
            charge = sale.charge
            net = billing.ledger.net_of(charge)
            if net > 0:
                billing.ledger.adjust(
                    actor=actor, charge=charge, delta=-net, kind="cancellation", reason=reason
                )
        audit.record(
            actor,
            "store.sale.reverse",
            sale,
            after={"reversed_on": today.isoformat(), "total": sale.total},
            reason=reason,
            branch_id=sale.branch_id,
            only_changes=False,
        )
        events.publish(SaleReversed(sale_id=sale.pk, reversal_id=reversal.pk))
    return reversal
