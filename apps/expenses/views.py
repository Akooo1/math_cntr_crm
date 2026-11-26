from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.core import dates, listing
from apps.core.permissions import has_perm, perm_required

from . import selectors, services
from .forms import ExpenseForm, ReverseForm
from .models import Category, Expense


def _date(raw: str | None):
    try:
        return dates.parse_date(raw or "")
    except ValueError:
        return None


def _add_errors(form, exc: ValidationError):
    for msg in exc.messages:
        form.add_error(None, msg)


@perm_required("expenses.view")
def expense_list(request):
    everything = selectors.expenses_for(request.user, request.branch_filter)
    qs = everything
    start = _date(request.GET.get("dan")) or dates.today().replace(day=1)
    end = _date(request.GET.get("gacha")) or dates.today()
    qs = qs.filter(spent_on__gte=start, spent_on__lte=end)
    category = request.GET.get("tur")
    if category:
        qs = qs.filter(category_id=category)
    if request.GET.get("joy") == "markaz":
        qs = qs.filter(branch__isnull=True)
    page, query = listing.paginate(request, qs)
    totals = listing.totals(everything, qs, amount=selectors.net_total(qs), amount_label=_("Total"))
    return render(
        request,
        "expenses/list.html",
        {
            "page": page,
            "query": query,
            "totals": totals,
            "start": start,
            "end": end,
            "category": category,
            "categories": Category.objects.all(),
            "can_create": has_perm(request.user, "expenses.create"),
            "show_center": has_perm(request.user, "expenses.shared"),
            "cancelled": set(
                qs.filter(kind=Expense.Kind.EXPENSE, reversed_by__isnull=False).values_list(
                    "pk", flat=True
                )
            ),
        },
    )


@perm_required("expenses.create")
def expense_create(request):
    form = ExpenseForm(request.POST or None, user=request.user, branch_filter=request.branch_filter)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            expense = services.record(
                actor=request.user,
                branch=d["branch"],
                category=d["category"],
                amount=d["amount"],
                spent_on=d["spent_on"],
                method=d["method"],
                note=d["note"],
            )
        except ValidationError as exc:
            _add_errors(form, exc)
        else:
            messages.success(request, _("Expense saved."))
            return redirect("expenses:detail", pk=expense.pk)
    return render(request, "expenses/form.html", {"form": form})


@perm_required("expenses.view")
def expense_detail(request, pk):
    expense = selectors.get_expense(request.user, pk)
    reversal = Expense.objects.filter(reverses=expense).select_related("created_by").first()
    form = None
    if has_perm(request.user, "expenses.reverse") and expense.kind == "expense" and not reversal:
        form = ReverseForm()
    return render(
        request,
        "expenses/detail.html",
        {"expense": expense, "reversal": reversal, "form": form},
    )


@perm_required("expenses.reverse")
def expense_reverse(request, pk):
    expense = selectors.get_expense(request.user, pk)
    form = ReverseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.reverse(
                actor=request.user, expense=expense, reason=form.cleaned_data["reason"]
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, _("Expense cancelled."))
    return redirect("expenses:detail", pk=expense.pk)
