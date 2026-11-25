"""Thin views: parse input, call one service or selector, render (docs/SPEC.md 17.7)."""

import datetime as dt

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.billing import selectors as billing_selectors
from apps.core import dates
from apps.core.money import format_som
from apps.core.permissions import has_perm, perm_required
from apps.core.system_settings import get_setting
from apps.students import selectors as student_selectors
from apps.students.models import Enrollment

from . import selectors, services
from .forms import CorrectionForm, ReceiveForm, ReverseForm
from .models import Product


def _date(raw):
    try:
        return dates.parse_date(raw) if raw else None
    except ValueError:
        return None


def _branch(request):
    raw = request.GET.get("filial") or request.POST.get("filial")
    return selectors.pick_branch(request.user, raw, request.branch_filter)


def _choose_branch(request, title, branches):
    return render(
        request,
        "store/choose_branch.html",
        {"title": title, "branches": branches, "path": request.path},
    )


def _fail(request, exc: ValidationError):
    messages.error(request, " ".join(exc.messages))


# --- Sell screen -----------------------------------------------------------------------------


def _basket(post) -> list[tuple[int, int]]:
    out = []
    for key, value in post.items():
        if key.startswith("q_"):
            try:
                pk, qty = int(key[2:]), int(value)
            except ValueError:
                continue
            if qty > 0:
                out.append((pk, qty))
    return out


@perm_required("store.sell")
def sell(request):
    branch, branches = _branch(request)
    if branch is None:
        return _choose_branch(request, _("Sales"), branches)
    back = f"{reverse('store:sell')}?filial={branch.pk}"
    if request.method == "POST":
        products = Product.objects.in_bulk([pk for pk, _q in _basket(request.POST)])
        lines = [(products[pk], q) for pk, q in _basket(request.POST) if pk in products]
        method = billing_selectors.cash_methods_for_entry().filter(
            pk=request.POST.get("method") or 0
        )
        try:
            if not method:
                raise ValidationError(_("Choose the payment method."))
            sale = services.sell_items(
                actor=request.user, branch=branch, lines=lines, method=method.first()
            )
        except ValidationError as exc:
            _fail(request, exc)
        else:
            messages.success(request, _("Sold: %(total)s.") % {"total": format_som(sale.total)})
        return redirect(back)
    methods = list(billing_selectors.cash_methods_for_entry())
    today = dates.today()
    tiles = selectors.sell_tiles(request.user, branch)
    return render(
        request,
        "store/sell.html",
        {
            "branch": branch,
            "branches": branches,
            "tiles": tiles,
            "tiles_data": [
                {"id": t.product.pk, "price": t.price.amount, "stock": max(t.on_hand, 0)}
                for t in tiles
            ],
            "methods": methods,
            "default_method": next((m for m in methods if m.name == "Naqd"), None)
            or (methods[0] if methods else None),
            "sales": selectors.sales_on(request.user, branch.pk, today),
            "today": today,
            "closed": billing_selectors.is_day_closed(branch.pk, today),
        },
    )


@perm_required("store.view")
def journal(request):
    today = dates.today()
    start = _date(request.GET.get("dan")) or today
    end = _date(request.GET.get("gacha")) or start
    if end < start:
        start, end = end, start
    qs = selectors.sales_for(request.user, request.branch_filter).filter(
        sold_on__gte=start, sold_on__lte=end
    )
    sales = list(qs[:500])
    return render(
        request,
        "store/journal.html",
        {
            "sales": sales,
            "start": start,
            "end": end,
            "prev": start - dt.timedelta(days=1),
            "next": start + dt.timedelta(days=1),
            "total": sum(s.total for s in sales if not hasattr(s, "reversal")),
        },
    )


@perm_required("store.view")
def sale_detail(request, pk):
    sale = selectors.get_sale(request.user, pk)
    return render(
        request,
        "store/sale.html",
        {
            "sale": sale,
            "can_reverse": has_perm(request.user, "store.sale.reverse")
            and not hasattr(sale, "reversal"),
        },
    )


@perm_required("store.sale.reverse")
def sale_reverse(request, pk):
    sale = selectors.get_sale(request.user, pk)
    form = ReverseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.reverse_sale(actor=request.user, sale=sale, reason=form.cleaned_data["reason"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("The sale is cancelled."))
            return redirect("store:sale", pk=sale.pk)
    return render(
        request,
        "store/simple_form.html",
        {
            "form": form,
            "title": _("Cancel the sale"),
            "hint": _(
                "The whole sale is cancelled today and the stock comes back. Money paid now is "
                "shown as paid out in today's cash report; a book on account is removed from "
                "the student's charges."
            ),
            "back": reverse("store:sale", args=[sale.pk]),
            "danger": True,
            "submit": _("Cancel the sale"),
        },
    )


# --- Stock -----------------------------------------------------------------------------------


@perm_required("store.view")
def stock(request):
    branch, branches = _branch(request)
    if branch is None:
        return _choose_branch(request, _("Stock"), branches)
    return render(
        request,
        "store/stock.html",
        {
            "branch": branch,
            "branches": branches,
            "rows": selectors.stock_rows(request.user, branch),
        },
    )


@perm_required("store.view")
def product_history(request, pk):
    product = selectors.get_product(request.user, pk)
    branch, branches = _branch(request)
    return render(
        request,
        "store/product.html",
        {
            "product": product,
            "branch": branch,
            "branches": branches,
            "moves": selectors.movements(request.user, product, branch.pk if branch else None),
            "show_cost": has_perm(request.user, "store.cost.view"),
        },
    )


def _stock_form(request, form_class, title, hint, save):
    branch, branches = _branch(request)
    if branch is None:
        return _choose_branch(request, title, branches)
    back = f"{reverse('store:stock')}?filial={branch.pk}"
    initial = {"product": request.GET.get("mahsulot")} if request.GET.get("mahsulot") else None
    form = form_class(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            save(branch, form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Saved."))
            return redirect(back)
    return render(
        request,
        "store/simple_form.html",
        {
            "form": form,
            "title": title,
            "hint": hint,
            "back": back,
            "branch": branch,
            "submit": _("Save"),
        },
    )


@perm_required("store.stock.receive")
def receive(request):
    def save(branch, d):
        services.receive_stock(
            actor=request.user,
            branch=branch,
            product=d["product"],
            quantity=d["quantity"],
            received_on=d["received_on"],
            purchase_cost=d["purchase_cost"],
            note=d["note"],
        )

    return _stock_form(
        request,
        ReceiveForm,
        _("Stock received"),
        _("Record what arrived at this branch."),
        save,
    )


@perm_required("store.stock.correct")
def correct(request):
    def save(branch, d):
        services.correct_stock(
            actor=request.user,
            branch=branch,
            product=d["product"],
            counted=d["counted"],
            reason=d["reason"],
        )

    return _stock_form(
        request,
        CorrectionForm,
        _("Stock correction"),
        _("Enter what you counted on the shelf. The difference is recorded with the reason."),
        save,
    )


# --- Books -----------------------------------------------------------------------------------


@perm_required("store.sell")
def give_book(request, student_id):
    student = student_selectors.get_student(request.user, student_id)
    back = reverse("students:detail", args=[student.pk])
    books = selectors.books_for_giving(request.user, student.branch)
    methods = list(billing_selectors.cash_methods_for_entry())
    error = ""
    if request.method == "POST":
        product = Product.objects.filter(pk=request.POST.get("book") or 0).first()
        try:
            qty = int(request.POST.get("quantity") or 1)
        except ValueError:
            qty = 0
        method = None
        if request.POST.get("pay") == "now":
            method = next((m for m in methods if str(m.pk) == request.POST.get("method")), None)
        try:
            if product is None:
                raise ValidationError(_("Choose an active book."))
            if request.POST.get("pay") == "now" and method is None:
                raise ValidationError(_("Choose the payment method."))
            services.give_book(
                actor=request.user, student=student, product=product, quantity=qty, method=method
            )
        except ValidationError as exc:
            error = " ".join(exc.messages)
        else:
            messages.success(request, _("The book is given."))
            return redirect(back)
    return render(
        request,
        "store/give_book.html",
        {
            "student": student,
            "books": books,
            "methods": methods,
            "error": error,
            "back": back,
            "due": dates.today() + dt.timedelta(days=get_setting("store.book_due_days")),
            "post": request.POST,
        },
    )


@perm_required("store.sell")
def give_group(request):
    groups = student_selectors.groups_for(request.user, request.branch_filter).exclude(
        status="finished"
    )
    group = None
    raw = request.GET.get("guruh") or request.POST.get("guruh")
    if raw:
        try:
            group = student_selectors.get_group(request.user, int(raw))
        except ValueError as exc:
            raise Http404 from exc
    error = ""
    if group is not None and request.method == "POST":
        product = Product.objects.filter(pk=request.POST.get("book") or 0).first()
        ids = [int(x) for x in request.POST.getlist("student") if x.isdigit()]
        try:
            if product is None:
                raise ValidationError(_("Choose an active book."))
            sales = services.give_books_to_group(
                actor=request.user, group=group, product=product, student_ids=ids
            )
        except ValidationError as exc:
            error = " ".join(exc.messages)
        else:
            messages.success(request, _("Books given: %(n)d.") % {"n": len(sales)})
            return redirect(f"{reverse('store:give_group')}?guruh={group.pk}")
    enrollments = []
    books = []
    if group is not None:
        enrollments = list(
            Enrollment.objects.filter(group=group, status__in=Enrollment.OPEN)
            .select_related("student")
            .order_by("student__last_name", "student__first_name")
        )
        books = selectors.books_for_giving(request.user, group.branch)
    return render(
        request,
        "store/give_group.html",
        {
            "groups": groups.order_by("name"),
            "group": group,
            "enrollments": enrollments,
            "books": books,
            "error": error,
            "due": dates.today() + dt.timedelta(days=get_setting("store.book_due_days")),
            "post": request.POST,
        },
    )
