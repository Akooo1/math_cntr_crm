import datetime as dt
from dataclasses import dataclass

from django.db.models import Count, F, Max, Min, Q, Sum
from django.http import Http404

from apps.core import dates
from apps.core.permissions import apply_branch_filter, has_perm, require_perm, scope_by_branch
from apps.core.system_settings import get_setting

from .models import (
    CashDayClose,
    Charge,
    ChargeNet,
    DiscountAssignment,
    InstallmentPlan,
    InstallmentTemplate,
    Payment,
    PaymentMethod,
    Price,
    StudentBalance,
)


def effective_price(
    *, course_id: int, kind: str, on_date: dt.date, branch_id: int | None, group_id=None
):
    """Price in force on `on_date` (SPEC 5.6): the most specific scope wins (group, then
    branch, then all branches); within a scope the latest effective_from <= on_date, then
    the latest created.
    """
    base = Price.objects.filter(course_id=course_id, kind=kind, effective_from__lte=on_date)
    scopes = []
    if group_id is not None:
        scopes.append(base.filter(group_id=group_id))
    if branch_id is not None:
        scopes.append(base.filter(branch_id=branch_id, group__isnull=True))
    scopes.append(base.filter(branch__isnull=True, group__isnull=True))
    for qs in scopes:
        price = qs.order_by("-effective_from", "-created_at", "-id").first()
        if price is not None:
            return price
    return None


def price_history(course_id: int):
    return Price.objects.filter(course_id=course_id).select_related("branch", "group", "created_by")


def rule_for(template: InstallmentTemplate):
    from .domain.installments import TemplateRule

    return TemplateRule(
        parts_count=template.parts_count,
        split_mode=template.split_mode,
        first_due=template.first_due,
        interval_months=template.interval_months,
        due_day_of_month=template.due_day_of_month,
        shares_bp=tuple(template.shares_bp()) if template.split_mode == "custom" else (),
    )


def is_day_closed(branch_id: int, day: dt.date) -> bool:
    """Public check for other modules (the store refuses sales on a closed cash day)."""
    return CashDayClose.objects.filter(branch_id=branch_id, date=day).exists()


def cash_methods_for_entry():
    """Methods a cashier can take money with at the desk (counted in the cash report)."""
    return payment_methods_for_entry().filter(included_in_cash_close=True)


def payment_methods_for_entry():
    from .providers import selectable_providers

    codes = [p.code for p in selectable_providers()]
    return PaymentMethod.objects.filter(is_active=True, provider_code__in=codes)


# =========================================================================================
# Ledger reads (all branch-scoped; finance only for roles with billing.view)
# =========================================================================================


def balance(student_id: int) -> int:
    """Negative = debt, positive = credit (avans). Always computed, never stored."""
    row = StudentBalance.objects.filter(pk=student_id).first()
    return row.balance if row else 0


def overdue_cutoff() -> dt.date:
    """A charge is overdue when its due date is before this day (grace days applied)."""
    return dates.today() - dt.timedelta(days=get_setting("billing.grace_days"))


@dataclass
class Account:
    balance: int
    overdue: int
    open_total: int
    charges: list
    payments: list
    discounts: list
    plans: list


def account(user, student) -> Account:
    require_perm(user, "billing.view")
    charges = list(
        Charge.objects.filter(student=student)
        .select_related("group", "net_row", "created_by")
        .prefetch_related("discounts", "adjustments__created_by")
        .order_by("-due_date", "-id")
    )
    cutoff = overdue_cutoff()
    overdue = sum(max(c.net_row.open, 0) for c in charges if c.due_date < cutoff)
    open_total = sum(max(c.net_row.open, 0) for c in charges)
    payments = list(
        Payment.objects.filter(student=student)
        .select_related("method", "received_by", "reverses")
        .prefetch_related("reversed_by")
        .order_by("-paid_on", "-id")
    )
    discounts = list(
        DiscountAssignment.objects.filter(enrollment__student=student)
        .select_related("discount_type", "enrollment__group")
        .order_by("-valid_from")
    )
    plans = list(
        InstallmentPlan.objects.filter(enrollment__student=student).select_related(
            "enrollment__group"
        )
    )
    return Account(balance(student.pk), overdue, open_total, charges, payments, discounts, plans)


# --- Payment status (the only finance signal a Sotuv menejeri sees) -------------------------

STATUS_LABELS = {
    "paid": "bg-emerald-100 text-emerald-800",
    "debt": "bg-rose-100 text-rose-800",
    "waiting": "bg-amber-100 text-amber-900",
    "none": "bg-slate-100 text-slate-600",
}


def payment_statuses(student_ids: list[int]) -> dict[int, str]:
    """'debt' (overdue amount), 'paid', 'waiting' (charges but no payment yet), 'none'."""
    cutoff = overdue_cutoff()
    overdue = set(
        ChargeNet.objects.filter(
            student_id__in=student_ids, due_date__lt=cutoff, net__gt=F("paid")
        ).values_list("student_id", flat=True)
    )
    charged = set(
        ChargeNet.objects.filter(student_id__in=student_ids, net__gt=0).values_list(
            "student_id", flat=True
        )
    )
    paid = set(
        Payment.objects.filter(
            student_id__in=student_ids, kind="payment", status="confirmed"
        ).values_list("student_id", flat=True)
    )
    out = {}
    for sid in student_ids:
        if sid in overdue:
            out[sid] = "debt"
        elif sid in paid:
            out[sid] = "paid"
        elif sid in charged:
            out[sid] = "waiting"
        else:
            out[sid] = "none"
    return out


# --- Debtors (Qarzdorlar) ------------------------------------------------------------------


def debtors(user, branch_filter=None, *, group=None, course=None, teacher=None, min_days=0):
    """[{student, overdue, open, days, oldest_due, last_payment}] sorted by overdue amount.

    The group / course / teacher filters match the CHARGES behind the debt (SPEC 6.4.7).
    """
    require_perm(user, "billing.debtors.view")
    cutoff = overdue_cutoff()
    rows = ChargeNet.objects.filter(net__gt=F("paid"))
    rows = apply_branch_filter(scope_by_branch(rows, user), branch_filter)
    if group:
        rows = rows.filter(group_id=group)
    if course:
        rows = rows.filter(course_id=course)
    if teacher:
        rows = rows.filter(group__teacher_id=teacher)
    overdue_rows = rows.filter(due_date__lt=cutoff)
    by_student = {
        r["student_id"]: r
        for r in overdue_rows.values("student_id").annotate(
            overdue=Sum(F("net") - F("paid")), oldest=Min("due_date"), n=Count("charge_id")
        )
    }
    open_totals = dict(
        rows.filter(student_id__in=by_student)
        .values("student_id")
        .annotate(t=Sum(F("net") - F("paid")))
        .values_list("student_id", "t")
    )
    last_paid = dict(
        Payment.objects.filter(student_id__in=by_student, kind="payment", status="confirmed")
        .values("student_id")
        .annotate(d=Max("paid_on"))
        .values_list("student_id", "d")
    )
    from apps.students.models import Enrollment, Student

    students = Student.objects.in_bulk(list(by_student))
    groups: dict[int, list[str]] = {}
    for sid, name in Enrollment.objects.filter(
        student_id__in=by_student, status__in=Enrollment.OPEN
    ).values_list("student_id", "group__name"):
        groups.setdefault(sid, []).append(name)
    today = dates.today()
    result = []
    for sid, r in by_student.items():
        days = (today - r["oldest"]).days
        if days < min_days:
            continue
        result.append(
            {
                "student": students[sid],
                "overdue": r["overdue"],
                "open": open_totals.get(sid, r["overdue"]),
                "oldest_due": r["oldest"],
                "days": days,
                "last_payment": last_paid.get(sid),
                "groups": groups.get(sid, []),
            }
        )
    result.sort(key=lambda x: (-x["overdue"], -x["days"]))
    return result


# --- Payments journal and cash days ------------------------------------------------------


def parent_view(student_id: int) -> dict:
    """What a connected parent may see about their own child in the Telegram bot (no user
    scope; the bot matched the parent by phone): balance, overdue amount, the next unpaid
    charge and the last payments."""
    cutoff = overdue_cutoff()
    unpaid = ChargeNet.objects.filter(student_id=student_id, net__gt=F("paid"))
    overdue = unpaid.filter(due_date__lt=cutoff).aggregate(t=Sum(F("net") - F("paid")))["t"]
    nxt = (
        unpaid.filter(due_date__gte=cutoff)
        .order_by("due_date", "charge_id")
        .values("due_date", "net", "paid")
        .first()
    )
    payments = list(
        Payment.objects.filter(student_id=student_id, kind="payment", status="confirmed")
        .select_related("method")
        .order_by("-paid_on", "-id")[:5]
    )
    reversed_ids = set(
        Payment.objects.filter(reverses__in=payments).values_list("reverses_id", flat=True)
    )
    return {
        "balance": balance(student_id),
        "overdue": int(overdue or 0),
        "next_due": nxt["due_date"] if nxt else None,
        "next_amount": int(nxt["net"] - nxt["paid"]) if nxt else 0,
        "payments": [(p, p.pk in reversed_ids) for p in payments],
    }


def overdue_summary() -> dict[int, dict]:
    """System-wide (no user scope; for scheduled jobs): {student_id: {"overdue", "oldest",
    "branch_id"}} for every student with an overdue unpaid charge right now."""
    rows = ChargeNet.objects.filter(net__gt=F("paid"), due_date__lt=overdue_cutoff())
    out: dict[int, dict] = {}
    for r in rows.values("student_id").annotate(
        overdue=Sum(F("net") - F("paid")), oldest=Min("due_date")
    ):
        out[r["student_id"]] = {"overdue": int(r["overdue"]), "oldest": r["oldest"]}
    branches = dict(
        rows.filter(student_id__in=out).order_by("-due_date").values_list("student_id", "branch_id")
    )
    for sid, d in out.items():
        d["branch_id"] = branches.get(sid)
    return out


def payments_for(user, branch_filter=None):
    require_perm(user, "billing.view")
    qs = Payment.objects.select_related("student", "method", "received_by", "branch", "reverses")
    return apply_branch_filter(scope_by_branch(qs, user), branch_filter)


def get_payment(user, pk) -> Payment:
    payment = payments_for(user).filter(pk=pk).first()
    if payment is None:
        raise Http404
    return payment


def unclosed_days(user, branch_filter=None, days=14) -> list[dict]:
    """Recent past days with cash-report payments that nobody closed."""
    if not has_perm(user, "billing.cash.view"):
        return []
    since = dates.today() - dt.timedelta(days=days)
    qs = Payment.objects.filter(
        paid_on__gte=since, paid_on__lt=dates.today(), method__included_in_cash_close=True
    )
    qs = apply_branch_filter(scope_by_branch(qs, user), branch_filter)
    pairs = set(qs.values_list("branch_id", "paid_on"))
    from apps.core.permissions import accessible_branch_ids

    from .services.cash import cash_sources

    allowed = accessible_branch_ids(user)
    for source in cash_sources():
        if source.active_days is None:
            continue
        for b, d in source.active_days(since, dates.today() - dt.timedelta(days=1)):
            if (allowed is None or b in allowed) and (
                branch_filter is None or b == int(branch_filter)
            ):
                pairs.add((b, d))
    closed = set(CashDayClose.objects.filter(date__gte=since).values_list("branch_id", "date"))
    from apps.settings.models import Branch

    names = dict(Branch.objects.values_list("id", "name"))
    return [
        {"branch_id": b, "branch": names.get(b, ""), "date": d}
        for b, d in sorted(pairs - closed, key=lambda x: (x[1], x[0]))
    ]


def collections_by_method(user, branch_filter, day: dt.date) -> list[dict]:
    qs = Payment.objects.filter(paid_on=day, status="confirmed")
    qs = apply_branch_filter(scope_by_branch(qs, user), branch_filter)
    rows = qs.values("method__name").annotate(
        inflow=Sum("amount", filter=Q(kind="payment")),
        outflow=Sum("amount", filter=~Q(kind="payment")),
    )
    return [
        {"method": r["method__name"], "net": (r["inflow"] or 0) - (r["outflow"] or 0)} for r in rows
    ]


def net_amount(payments) -> int:
    """Sum of a payments queryset as it affects accounts: payments in, reversals and refunds
    out (the same total as the payments Excel export)."""
    agg = payments.aggregate(
        inflow=Sum("amount", filter=Q(kind="payment")),
        outflow=Sum("amount", filter=~Q(kind="payment")),
    )
    return (agg["inflow"] or 0) - (agg["outflow"] or 0)
