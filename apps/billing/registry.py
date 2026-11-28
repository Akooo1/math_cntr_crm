from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.audit_display import register_labels as register_audit_labels
from apps.core.global_search import SearchHit, SearchProvider, register_search_provider
from apps.core.permissions import register_permission
from apps.core.registry import DashboardWidget, NavItem, registry
from apps.core.roles import Role
from apps.core.system_settings import SettingDef, register_setting
from apps.students import services as student_services

from . import sections  # noqa: F401 - registers Sozlamalar sections

D, A, M = Role.DIRECTOR, Role.BRANCH_ADMIN, Role.SALES_MANAGER

for code, label, roles in (
    ("billing.view", _("See finances"), {D, A}),
    ("billing.payment.create", _("Take payments"), {D, A}),
    ("billing.reverse", _("Reverse payments, refund, correct charges"), {D}),
    ("billing.discount.assign", _("Give discounts"), {D, A}),
    ("billing.discount.custom", _("Enter a custom discount value"), {D}),
    ("billing.plan.edit", _("Change installment plans"), {D, A}),
    ("billing.cash.view", _("See the cash report"), {D, A}),
    ("billing.cash.close", _("Close the cash day"), {D}),
    ("billing.cash.reopen", _("Reopen a closed cash day"), {D}),
    ("billing.debtors.view", _("See debtors"), {D, A}),
    ("billing.payment_status.view", _("See whether a student has paid"), {D, A, M}),
):
    register_permission(code, label, roles)

for item in (
    NavItem(
        key="payments",
        label=_("Payments"),
        url_name="billing:payments",
        icon="card",
        permission="billing.view",
        order=30,
        mobile_priority=16,
        active_prefix="/tolovlar/",
    ),
    NavItem(
        key="debtors",
        label=_("Debtors"),
        url_name="billing:debtors",
        icon="x-circle",
        permission="billing.debtors.view",
        order=31,
        mobile_priority=17,
        active_prefix="/qarzdorlar/",
    ),
    NavItem(
        key="cash",
        label=_("Cash desk"),
        url_name="billing:cash",
        icon="receipt",
        permission="billing.cash.view",
        order=32,
        mobile_priority=40,
        active_prefix="/kassa/",
    ),
):
    registry.add_nav(item)

register_setting(
    SettingDef(
        key="billing.rounding_step",
        label=_("Rounding of computed amounts"),
        help_text=_(
            "Prorated amounts, percent discounts and installment parts are rounded to this."
        ),
        default=1000,
        choices=((1, _("1 so'm")), (100, _("100 so'm")), (1000, _("1 000 so'm"))),
        order=10,
    )
)
register_setting(
    SettingDef(
        key="billing.monthly_due_day",
        label=_("Monthly fee due day"),
        help_text=_("Day of the month the monthly fee is due."),
        default=10,
        min_value=1,
        max_value=28,
        order=20,
    )
)
register_setting(
    SettingDef(
        key="billing.backdate_days",
        label=_("Payment backdating window (days)"),
        help_text=_("How many days back a payment date may be. Closed days are always locked."),
        default=3,
        min_value=0,
        max_value=31,
        order=30,
    )
)
register_setting(
    SettingDef(
        key="billing.grace_days",
        label=_("Grace period before debt (days)"),
        help_text=_("Days after the due date before a student appears in the debtors list."),
        default=0,
        min_value=0,
        max_value=60,
        order=40,
    )
)


register_audit_labels(
    {
        "net": _("Amount"),
        "price": _("Price"),
        "plan": _("Installment plan"),
        "reverses": _("Reverses"),
        "reversal": _("Reversal"),
        "ended_by": _("Ended by"),
        "ended_at": _("Ended at"),
        "parts": _("Parts"),
        "shares_bp": _("Shares of each part (%)"),
        "total_in": _("Received"),
        "total_out": _("Paid out"),
        "total_net": _("Net"),
        "count": _("Count"),
        "methods": _("Payment methods"),
        "month": _("Month"),
        "created": _("Charges created"),
        "no_price": _("Without a price"),
        "charge": _("Charge"),
        "payment": _("Payment"),
        "assignment": _("Discount"),
        "discount_type": _("Discount type"),
        "totals": _("Totals"),
        "template": _("Installment template"),
        "part_no": _("Part"),
    }
)


# --- Hooks into the students module ---------------------------------------------------------


def _account_panel(request, student):
    from apps.core import dates

    from . import selectors

    return {
        "account": selectors.account(request.user, student),
        "student": student,
        "today": dates.today(),
    }


def _status_panel(request, student):
    from . import selectors

    return {"status": selectors.payment_statuses([student.pk])[student.pk]}


def _status_badges(user, students):
    from django.utils.translation import gettext

    from apps.core.permissions import has_perm

    from . import selectors

    if not has_perm(user, "billing.payment_status.view") or not students:
        return {}
    labels = {
        "paid": gettext("Paid"),
        "debt": gettext("Owes"),
        "waiting": gettext("Payment expected"),
        "none": "",
    }
    out = {}
    for sid, status in selectors.payment_statuses([s.pk for s in students]).items():
        if labels[status]:
            out[sid] = (labels[status], selectors.STATUS_LABELS[status])
    return out


def _pay_action(user, students):
    """'Take payment' button on student cards in the phone list."""
    from apps.core.permissions import has_perm

    if not has_perm(user, "billing.payment.create"):
        return {}
    base = reverse("billing:payment_create")
    return {
        s.pk: [student_services.ListAction(f"{base}?oquvchi={s.pk}", "card", _("Take payment"), 20)]
        for s in students
    }


def _register_hooks():
    from . import import_kinds
    from .enrollment import BillingExtension

    student_services.register_enrollment_extension(BillingExtension())
    student_services.register_profile_panel(
        student_services.ProfilePanel(
            key="billing_account",
            template="billing/panel_account.html",
            permission="billing.view",
            context=_account_panel,
            order=10,
        )
    )
    student_services.register_profile_panel(
        student_services.ProfilePanel(
            key="billing_status",
            template="billing/panel_status.html",
            permission="billing.payment_status.view",
            context=_status_panel,
            order=11,
        )
    )
    student_services.register_list_badge(_status_badges)
    student_services.register_list_action(_pay_action)
    import_kinds.register()


_register_hooks()


def _today_cash(request):
    from apps.core import dates

    from . import selectors

    rows = selectors.collections_by_method(request.user, request.branch_filter, dates.today())
    return {
        "rows": rows,
        "total": sum(r["net"] for r in rows),
        "unclosed": selectors.unclosed_days(request.user, request.branch_filter),
    }


def _debt(request):
    from . import selectors

    rows = selectors.debtors(request.user, request.branch_filter)
    return {"count": len(rows), "total": sum(r["overdue"] for r in rows), "top": rows[:5]}


registry.add_widget(
    DashboardWidget(
        "billing_today", "billing/widgets/today.html", "billing.cash.view", 1, _today_cash
    )
)
registry.add_widget(
    DashboardWidget("billing_debt", "billing/widgets/debt.html", "billing.debtors.view", 2, _debt)
)


# --- Global search (Ctrl+K) -----------------------------------------------------------


def _search_payments(request, query, limit):
    """By receipt number, or by the student's name or phone."""
    from django.db.models import Q

    from apps.core.dates import format_date
    from apps.core.money import format_som
    from apps.core.search import text_search

    from . import selectors

    qs = selectors.payments_for(request.user, request.branch_filter)
    by_receipt = qs.filter(receipt_number__icontains=query.replace(" ", ""))
    by_student = text_search(
        qs, query, ["student__last_name", "student__first_name"], ["student__phone"]
    )
    ids = list(by_receipt.values_list("pk", flat=True)[:limit]) + list(
        by_student.values_list("pk", flat=True)[:limit]
    )
    hits = []
    for p in qs.filter(Q(pk__in=ids))[:limit]:
        amount = format_som(p.signed_amount)
        hits.append(
            SearchHit(
                title=f"{p.receipt_number} · {p.student.full_name}",
                url=reverse("billing:payment", args=[p.pk]),
                subtitle=" · ".join((format_date(p.paid_on), amount, p.method.name)),
            )
        )
    return hits


register_search_provider(
    SearchProvider("payments", _("Payments"), "card", "billing.view", _search_payments, 40)
)
