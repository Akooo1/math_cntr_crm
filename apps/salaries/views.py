from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core import dates, excel, listing
from apps.core.permissions import perm_required

from . import selectors, services
from .forms import AdjustmentForm, PayoutForm, ReasonForm
from .models import Adjustment, Payout


def _month(request):
    raw = request.GET.get("oy") or request.POST.get("oy")
    month = selectors.parse_month(raw)
    if month is None or month < selectors.start_month():
        return selectors.open_month()
    return month


def _month_url(name, month, **kwargs):
    return f"{reverse(name, kwargs=kwargs)}?oy={month:%m.%Y}"


def _teacher(pk):
    return get_object_or_404(get_user_model(), pk=pk, role__in=selectors.SALARIED_ROLES)


def _messages_from(request, exc):
    messages.error(request, " ".join(exc.messages))


@perm_required("salaries.manage")
def index(request):
    month = _month(request)
    data = selectors.month_overview(request.user, month)
    if request.GET.get("excel"):
        return _excel(data)
    return render(
        request,
        "salaries/index.html",
        {
            **data,
            "months": selectors.months_for_picker(),
            "totals": listing.totals(
                len(data["sheets"]), amount=data["grand"].total, amount_label=_("To pay")
            ),
        },
    )


def _excel(data):
    headers = [
        _("Employee"),
        _("Money paid"),
        _("Share"),
        _("Corrections"),
        _("Fixed salary"),
        _("Bonuses"),
        _("Deductions"),
        _("Total"),
        _("Salary given"),
    ]
    rows = [
        [
            s.teacher.full_name,
            s.totals.paid,
            s.totals.share,
            s.totals.corrections,
            s.totals.fixed,
            s.totals.bonuses,
            s.totals.deductions,
            s.totals.total,
            s.payout.paid_on if s.payout else "",
        ]
        for s in data["sheets"]
    ]
    g = data["grand"]
    totals = [
        _("Total"),
        g.paid,
        g.share,
        g.corrections,
        g.fixed,
        g.bonuses,
        g.deductions,
        g.total,
        "",
    ]
    kinds = ["text", "money", "money", "money", "money", "money", "money", "money", "date"]
    content = excel.workbook(_("Salaries"), headers, rows, kinds, totals)
    return excel.response(f"maosh-{data['month']:%Y-%m}", content)


@perm_required("salaries.manage")
@require_POST
def close(request):
    month = _month(request)
    try:
        services.close_month(actor=request.user, month=month)
    except ValidationError as exc:
        _messages_from(request, exc)
    else:
        messages.success(request, _("The month is closed. Its salaries are frozen."))
    return redirect(_month_url("salaries:index", month))


def _sheet_page(request, teacher_id, template):
    month = _month(request)
    sheet = selectors.sheet(request.user, teacher_id, month)
    return render(
        request,
        template,
        {
            "sheet": sheet,
            "month": month,
            "months": selectors.months_for_picker(),
            "adjustment_form": AdjustmentForm(),
            "payout_form": PayoutForm(initial={"paid_on": dates.today()}),
            "reason_form": ReasonForm(),
        },
    )


@perm_required("salaries.manage")
def sheet(request, pk):
    return _sheet_page(request, pk, "salaries/sheet.html")


@perm_required("salaries.view_own")
def mine(request):
    if request.GET.get("oy"):
        return _sheet_page(request, request.user.pk, "salaries/sheet.html")
    return render(
        request,
        "salaries/mine.html",
        {"months": selectors.own_months(request.user)},
    )


@perm_required("salaries.manage")
@require_POST
def adjustment_add(request, pk):
    teacher, month = _teacher(pk), _month(request)
    form = AdjustmentForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            services.add_adjustment(
                actor=request.user,
                teacher=teacher,
                month=month,
                kind=d["kind"],
                amount=d["amount"],
                reason=d["reason"],
            )
        except ValidationError as exc:
            _messages_from(request, exc)
        else:
            messages.success(request, _("Saved."))
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect(_month_url("salaries:sheet", month, pk=teacher.pk))


@perm_required("salaries.manage")
@require_POST
def adjustment_delete(request, pk):
    adj = get_object_or_404(Adjustment, pk=pk)
    try:
        services.delete_adjustment(actor=request.user, adjustment=adj)
    except ValidationError as exc:
        _messages_from(request, exc)
    else:
        messages.success(request, _("Deleted."))
    return redirect(_month_url("salaries:sheet", adj.month, pk=adj.teacher_id))


@perm_required("salaries.manage")
@require_POST
def payout(request, pk):
    teacher, month = _teacher(pk), _month(request)
    form = PayoutForm(request.POST)
    if form.is_valid():
        try:
            services.pay_out(
                actor=request.user,
                teacher=teacher,
                month=month,
                paid_on=form.cleaned_data["paid_on"],
                note=form.cleaned_data["note"],
            )
        except ValidationError as exc:
            _messages_from(request, exc)
        else:
            messages.success(request, _("The salary is marked as paid out."))
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect(_month_url("salaries:sheet", month, pk=teacher.pk))


@perm_required("salaries.manage")
@require_POST
def payout_cancel(request, pk):
    payout_row = get_object_or_404(Payout, pk=pk, kind=Payout.Kind.PAYOUT)
    form = ReasonForm(request.POST)
    month = payout_row.month.month
    if form.is_valid():
        try:
            services.cancel_payout(
                actor=request.user, payout=payout_row, reason=form.cleaned_data["reason"]
            )
        except ValidationError as exc:
            _messages_from(request, exc)
        else:
            messages.success(request, _("The payout is cancelled."))
    else:
        messages.error(request, _("Write the reason."))
    return redirect(_month_url("salaries:sheet", month, pk=payout_row.teacher_id))
