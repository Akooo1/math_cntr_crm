import datetime as dt

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core import dates, excel, listing, phone
from apps.core.money import parse_amount
from apps.core.permissions import (
    accessible_branch_ids,
    ensure_branch_access,
    has_perm,
    perm_required,
)
from apps.settings.models import Branch, Course
from apps.settings.selectors import receipt_details
from apps.students import selectors as student_selectors
from apps.students.models import Enrollment

from . import selectors, services
from .forms import (
    CashCloseForm,
    CorrectionForm,
    DiscountAssignForm,
    EndDateForm,
    ManualChargeForm,
    PaymentForm,
    ReasonForm,
    RefundForm,
)
from .models import CashDayClose, Charge, DiscountAssignment, InstallmentPlan, Payment
from .services import installments as plan_services


def _error(form, exc):
    form.add_error(None, exc)


def _branches_for(user):
    qs = Branch.objects.filter(is_active=True)
    ids = accessible_branch_ids(user)
    return qs if ids is None else qs.filter(pk__in=ids)


def _student(request, pk):
    student = student_selectors.get_student(request.user, pk)
    if not has_perm(request.user, "billing.view"):
        raise PermissionDenied
    return student


def _to_profile(student):
    return redirect("students:detail", pk=student.pk)


# --- Payments ---------------------------------------------------------------------------


@perm_required("billing.view")
def payment_list(request):
    everything = selectors.payments_for(request.user, request.branch_filter)
    qs = everything
    start = _date(request.GET.get("dan")) or dates.today() - dt.timedelta(days=30)
    end = _date(request.GET.get("gacha")) or dates.today()
    qs = qs.filter(paid_on__gte=start, paid_on__lte=end)
    if request.GET.get("usul"):
        qs = qs.filter(method_id=request.GET["usul"])
    if request.GET.get("excel"):
        rows = [
            [
                p.paid_on,
                p.receipt_number,
                p.student.full_name,
                p.get_kind_display(),
                p.method.name,
                p.signed_amount,
                p.branch.name,
                p.received_by.full_name,
                p.comment or p.reason,
            ]
            for p in qs
        ]
        headers = [
            _("Date"),
            _("Receipt"),
            _("Student"),
            _("Type"),
            _("Payment method"),
            _("Amount"),
            _("Branch"),
            _("Received by"),
            _("Comment"),
        ]
        kinds = ["date", "text", "text", "text", "text", "money", "text", "text", "text"]
        return excel.response(
            f"tolovlar-{start:%Y%m%d}-{end:%Y%m%d}",
            excel.workbook(
                _("Payments"),
                headers,
                rows,
                kinds,
                [_("Total"), "", "", "", "", sum(r[5] for r in rows), "", "", ""],
            ),
        )
    totals = listing.totals(everything, qs, amount=selectors.net_amount(qs))
    qs, sort = listing.sort_queryset(
        request,
        qs,
        {
            "sana": ("paid_on", "created_at", "id"),
            "summa": ("amount", "id"),
            "oquvchi": ("student__last_name", "student__first_name", "id"),
        },
        default="-sana",
    )
    page, query = listing.paginate(request, qs)
    return render(
        request,
        "billing/payment_list.html",
        {
            "page": page,
            "totals": totals,
            "sort": sort,
            "start": start,
            "end": end,
            "query": query,
            "methods": selectors.payment_methods_for_entry(),
        },
    )


def _date(raw):
    try:
        return dates.parse_date(raw) if raw else None
    except ValueError:
        return None


@perm_required("billing.payment.create")
def payment_create(request):
    student = None
    if request.GET.get("oquvchi") or request.POST.get("student"):
        student = _student(request, request.GET.get("oquvchi") or request.POST.get("student"))
    form = PaymentForm(
        request.POST or None,
        methods=selectors.payment_methods_for_entry(),
        branches=_branches_for(request.user),
        initial={"paid_on": dates.today()},
    )
    if request.method == "POST" and student and form.is_valid():
        d = form.cleaned_data
        try:
            payment = services.payments.record_payment(
                actor=request.user,
                student=student,
                amount=d["amount"],
                method=d["method"],
                paid_on=d["paid_on"],
                comment=d["comment"],
                branch=d.get("branch"),
            )
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(
                request, _("Payment saved. Receipt %(n)s.") % {"n": payment.receipt_number}
            )
            return redirect("billing:payment", pk=payment.pk)
    context = {"form": form, "student": student}
    if student:
        context["balance"] = selectors.balance(student.pk)
    return render(request, "billing/payment_form.html", context)


@perm_required("billing.payment.create")
def student_search(request):
    q = request.GET.get("q", "").strip()
    results = []
    if len(q) >= 2:
        qs = student_selectors.search_students(
            student_selectors.students_for(request.user, request.branch_filter), q
        )
        results = list(qs.order_by("last_name", "first_name")[:12])
    balances = {r.pk: selectors.balance(r.pk) for r in results}
    return render(
        request, "billing/_student_search.html", {"results": results, "balances": balances, "q": q}
    )


@perm_required("billing.view")
def payment_detail(request, pk):
    payment = selectors.get_payment(request.user, pk)
    return render(
        request,
        "billing/payment_detail.html",
        {
            "payment": payment,
            "allocations": payment.allocations.select_related("charge", "charge__group"),
            "reversal": Payment.objects.filter(reverses=payment).first(),
            "can_reverse": has_perm(request.user, "billing.reverse"),
        },
    )


@perm_required("billing.view")
def receipt(request, pk):
    payment = selectors.get_payment(request.user, pk)
    groups = Enrollment.objects.filter(
        student=payment.student, status__in=Enrollment.OPEN
    ).select_related("group")
    return render(
        request,
        "billing/receipt.html",
        {
            "p": payment,
            "info": receipt_details(payment.branch),
            "groups": [e.group.name for e in groups],
            "allocations": payment.allocations.select_related("charge", "charge__group"),
            "balance": selectors.balance(payment.student_id),
        },
    )


@perm_required("billing.reverse")
def payment_reverse(request, pk):
    payment = selectors.get_payment(request.user, pk)
    form = ReasonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.payments.reverse_payment(
                actor=request.user, payment=payment, reason=form.cleaned_data["reason"]
            )
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, _("The payment was reversed."))
            return redirect("billing:payment", pk=payment.pk)
    return render(
        request,
        "billing/simple_form.html",
        {
            "form": form,
            "title": _("Reverse payment %(n)s") % {"n": payment.receipt_number},
            "back": reverse("billing:payment", args=[payment.pk]),
            "danger": True,
            "hint": _(
                "The whole payment is cancelled with today's date. "
                "Enter the correct payment again afterwards."
            ),
        },
    )


@perm_required("billing.reverse")
def refund(request, pk):
    student = _student(request, pk)
    form = RefundForm(request.POST or None, methods=selectors.payment_methods_for_entry())
    credit = services.payments.credit_of(student.pk)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            services.payments.refund(
                actor=request.user,
                student=student,
                amount=d["amount"],
                method=d["method"],
                reason=d["reason"],
            )
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, _("The refund was saved."))
            return _to_profile(student)
    return render(
        request,
        "billing/simple_form.html",
        {
            "form": form,
            "title": _("Refund to %(name)s") % {"name": student.full_name},
            "back": reverse("students:detail", args=[student.pk]),
            "danger": True,
            "hint": _("Credit available for refund: %(credit)s")
            % {"credit": services.payments.money_text(credit)},
        },
    )


# --- Discounts, corrections, plans ----------------------------------------------------------


@perm_required("billing.discount.assign")
def discount_assign(request, pk):
    student = _student(request, pk)
    enrollments = Enrollment.objects.filter(
        student=student, status__in=Enrollment.OPEN
    ).select_related("group", "group__course")
    form = DiscountAssignForm(
        request.POST or None,
        enrollments=enrollments,
        can_custom=has_perm(request.user, "billing.discount.custom"),
        initial={"valid_from": dates.today()},
    )
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            services.discounts.assign(
                actor=request.user,
                enrollment=d["enrollment"],
                discount_type=d["discount_type"],
                valid_from=d["valid_from"],
                valid_to=d["valid_to"],
                value=form.custom_value() if "value_text" in form.fields else None,
                reason=d["reason"],
            )
        except (ValidationError, PermissionDenied) as exc:
            _error(
                form, exc if isinstance(exc, ValidationError) else ValidationError(_("No access"))
            )
        else:
            messages.success(
                request, _("Discount added. It applies to charges issued from now on.")
            )
            return _to_profile(student)
    return render(
        request,
        "billing/simple_form.html",
        {
            "form": form,
            "title": _("Add a discount: %(name)s") % {"name": student.full_name},
            "back": reverse("students:detail", args=[student.pk]),
            "hint": _(
                "Charges already issued don't change. "
                "To change one, ask the director for a correction."
            ),
        },
    )


@perm_required("billing.discount.assign")
def discount_end(request, pk):
    assignment = get_object_or_404(
        DiscountAssignment.objects.select_related("enrollment__student", "enrollment__group"), pk=pk
    )
    student = _student(request, assignment.enrollment.student_id)
    form = EndDateForm(request.POST or None, initial={"valid_to": dates.today()})
    if request.method == "POST" and form.is_valid():
        try:
            services.discounts.end(
                actor=request.user, assignment=assignment, valid_to=form.cleaned_data["valid_to"]
            )
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, _("Saved."))
            return _to_profile(student)
    return render(
        request,
        "billing/simple_form.html",
        {
            "form": form,
            "title": _("End the discount %(name)s") % {"name": assignment.discount_type.name},
            "back": reverse("students:detail", args=[student.pk]),
        },
    )


@perm_required("billing.reverse")
def charge_correct(request, pk):
    charge = get_object_or_404(Charge, pk=pk)
    student = _student(request, charge.student_id)
    current = services.ledger.net_of(charge)
    form = CorrectionForm(request.POST or None, initial={"new_net": current})
    if request.method == "POST" and form.is_valid():
        try:
            services.corrections.correct_charge(
                actor=request.user,
                charge=charge,
                new_net=form.cleaned_data["new_net"],
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, _("The charge was corrected."))
            return _to_profile(student)
    return render(
        request,
        "billing/simple_form.html",
        {
            "form": form,
            "title": _("Correct a charge"),
            "back": reverse("students:detail", args=[student.pk]),
            "hint": _("Current amount: %(a)s. The original stays in the history.")
            % {"a": services.payments.money_text(current)},
        },
    )


@perm_required("billing.reverse")
def manual_charge(request, pk):
    student = _student(request, pk)
    form = ManualChargeForm(request.POST or None, initial={"due_date": dates.today()})
    if request.method == "POST" and form.is_valid():
        try:
            services.corrections.manual_charge(
                actor=request.user, student=student, **form.cleaned_data
            )
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, _("Saved."))
            return _to_profile(student)
    return render(
        request,
        "billing/simple_form.html",
        {
            "form": form,
            "title": _("Additional charge: %(name)s") % {"name": student.full_name},
            "back": reverse("students:detail", args=[student.pk]),
        },
    )


@perm_required("billing.plan.edit")
def plan_edit(request, pk):
    plan = get_object_or_404(
        InstallmentPlan.objects.select_related("enrollment__student", "enrollment__group"), pk=pk
    )
    student = _student(request, plan.enrollment.student_id)
    parts = plan_services.open_parts(plan)
    rows = [{"charge": c, "net": services.ledger.net_of(c)} for c in parts]
    errors = []
    if request.method == "POST":
        changes = []
        for row in rows:
            c = row["charge"]
            try:
                amount = parse_amount(request.POST.get(f"amount_{c.pk}", row["net"]))
                due = dates.parse_date(
                    request.POST.get(f"due_{c.pk}") or dates.format_date(c.due_date)
                )
            except ValueError:
                errors.append(_("Check the amounts and dates."))
                break
            changes.append({"charge": c, "amount": amount, "due_date": due})
        if not errors:
            try:
                plan_services.edit_plan(
                    actor=request.user,
                    plan=plan,
                    changes=changes,
                    reason=request.POST.get("reason", ""),
                )
            except ValidationError as exc:
                errors.extend(exc.messages)
            else:
                messages.success(request, _("The installment plan was changed."))
                return _to_profile(student)
    return render(
        request,
        "billing/plan_edit.html",
        {
            "plan": plan,
            "rows": rows,
            "errors": errors,
            "student": student,
            "revisions": plan.revisions.select_related("created_by"),
            "reason": request.POST.get("reason", ""),
        },
    )


# --- Debtors and cash ---------------------------------------------------------------------


@perm_required("billing.debtors.view")
def debtors(request):
    def num(name):
        raw = request.GET.get(name) or ""
        return int(raw) if raw.isdigit() else None

    rows = selectors.debtors(
        request.user,
        request.branch_filter,
        group=num("guruh"),
        course=num("kurs"),
        teacher=num("oqituvchi"),
        min_days=num("kun") or 0,
    )
    if request.GET.get("excel"):
        headers = [
            _("Student"),
            _("Phone"),
            _("Parent's phone"),
            _("Groups"),
            _("Overdue"),
            _("Unpaid total"),
            _("Days overdue"),
            _("Oldest due date"),
            _("Last payment"),
        ]
        data = [
            [
                r["student"].full_name,
                phone.format_phone(r["student"].phone),
                phone.format_phone(r["student"].parent_phone),
                ", ".join(r["groups"]),
                r["overdue"],
                r["open"],
                r["days"],
                r["oldest_due"],
                r["last_payment"],
            ]
            for r in rows
        ]
        kinds = ["text", "text", "text", "text", "money", "money", "int", "date", "date"]
        totals = [
            _("Total"),
            "",
            "",
            "",
            sum(r["overdue"] for r in rows),
            sum(r["open"] for r in rows),
            "",
            "",
            "",
        ]
        return excel.response(
            f"qarzdorlar-{dates.today():%Y%m%d}",
            excel.workbook(_("Debtors"), headers, data, kinds, totals),
        )
    groups = student_selectors.groups_for(request.user, request.branch_filter).exclude(
        status="finished"
    )
    teachers = {g.teacher_id: g.teacher for g in groups}
    filtered = listing.active_filters(request, ["guruh", "kurs", "oqituvchi", "kun"])
    everyone = len(rows)
    if filtered:
        everyone = len(selectors.debtors(request.user, request.branch_filter))
    totals = listing.totals(
        everyone,
        len(rows),
        filtered=filtered,
        amount=sum(r["overdue"] for r in rows),
        amount_label=_("Overdue"),
    )
    rows, sort = listing.sort_rows(
        request,
        rows,
        {
            "qarz": lambda r: (r["overdue"], r["days"]),
            "kun": lambda r: (r["days"], r["overdue"]),
            "oquvchi": lambda r: (r["student"].last_name, r["student"].first_name),
        },
        default="-qarz",
    )
    return render(
        request,
        "billing/debtors.html",
        {
            "rows": rows,
            "totals": totals,
            "sort": sort,
            "total_overdue": totals.amount,
            "groups": groups,
            "courses": Course.objects.filter(is_active=True),
            "teachers": sorted(teachers.values(), key=lambda u: u.full_name),
            "f": {k: request.GET.get(k, "") for k in ("guruh", "kurs", "oqituvchi", "kun")},
        },
    )


def _cash_branch(request):
    branches = _branches_for(request.user)
    raw = request.GET.get("filial") or request.POST.get("filial") or request.branch_filter
    branch = branches.filter(pk=raw).first() if raw else None
    return branch or branches.first(), branches


@perm_required("billing.cash.view")
def cash_report(request):
    branch, branches = _cash_branch(request)
    if branch is None:
        raise Http404
    day = _date(request.GET.get("sana")) or dates.today()
    report = services.cash.day_report(branch.pk, day)
    if request.GET.get("excel"):
        headers = [
            _("Time"),
            _("Receipt"),
            _("Student"),
            _("Type"),
            _("Payment method"),
            _("Amount"),
            _("Received by"),
        ]
        data = [
            [
                timezone.localtime(p.created_at).strftime("%H:%M"),
                p.receipt_number,
                p.student.full_name,
                p.get_kind_display(),
                p.method.name,
                p.signed_amount,
                p.received_by.full_name,
            ]
            for p in report["rows"]
        ]
        kinds = ["text", "text", "text", "text", "text", "money", "text"]
        totals = [_("Total"), "", "", "", "", report["total_net"], ""]
        return excel.response(
            f"kassa-{branch.receipt_prefix}-{day:%Y%m%d}",
            excel.workbook(_("Cash report"), headers, data, kinds, totals),
        )
    closed = (
        CashDayClose.objects.filter(branch=branch, date=day).select_related("closed_by").first()
    )
    return render(
        request,
        "billing/cash.html",
        {
            "branch": branch,
            "branches": branches,
            "day": day,
            "report": report,
            "totals": listing.totals(len(report["rows"]), amount=report["total_net"]),
            "closed": closed,
            "prev": day - dt.timedelta(days=1),
            "next": day + dt.timedelta(days=1),
            "can_close": has_perm(request.user, "billing.cash.close")
            and not closed
            and day <= dates.today(),
            "form": CashCloseForm(),
            "unclosed": selectors.unclosed_days(request.user, branch.pk),
        },
    )


@perm_required("billing.cash.close")
@require_POST
def cash_close(request):
    branch, _branches = _cash_branch(request)
    if branch is None:
        raise Http404
    ensure_branch_access(request.user, branch.pk)
    day = _date(request.POST.get("sana")) or dates.today()
    form = CashCloseForm(request.POST)
    form.is_valid()
    try:
        services.cash.close_day(
            actor=request.user, branch=branch, day=day, note=form.cleaned_data.get("note", "")
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("The day is closed. Its payments are locked."))
    return redirect(f"{reverse('billing:cash')}?filial={branch.pk}&sana={dates.format_date(day)}")
