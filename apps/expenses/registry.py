from django.utils.translation import gettext_lazy as _

from apps.billing.services.cash import CashSource, register_cash_source
from apps.core.audit_display import register_labels as register_audit_labels
from apps.core.permissions import register_permission
from apps.core.registry import NavItem, registry
from apps.core.reports import ReportDef, register_report
from apps.core.roles import Role

from . import sections  # noqa: F401 - registers Sozlamalar sections

D, A = Role.DIRECTOR, Role.BRANCH_ADMIN

for code, label, roles in (
    ("expenses.view", _("See expenses"), {D, A}),
    ("expenses.create", _("Record expenses"), {D, A}),
    ("expenses.shared", _("Record center-wide expenses"), {D}),
    ("expenses.reverse", _("Cancel expenses"), {D}),
    ("expenses.profit", _("See branch profit"), {D}),
):
    register_permission(code, label, roles)

registry.add_nav(
    NavItem(
        key="expenses",
        label=_("Expenses"),
        url_name="expenses:list",
        icon="receipt",
        permission="expenses.view",
        order=46,
        mobile_priority=70,
        active_prefix="/xarajatlar/",
    )
)


def _cash_lines(branch_id, day):
    from . import selectors

    return selectors.cash_lines(branch_id, day)


def _cash_days(since, until):
    from . import selectors

    return selectors.cash_active_days(since, until)


register_cash_source(
    CashSource(
        code="expenses", label=_("Expenses"), lines=_cash_lines, active_days=_cash_days, order=20
    )
)


def _profit(user, p):
    from . import selectors

    return selectors.profit_report(user, p)


register_report(
    ReportDef(
        "filial-foydasi",
        _("Branch profit"),
        _("Money in minus salaries, purchase cost and expenses, per branch."),
        "expenses.profit",
        _profit,
        order=5,
        group=_("Finance"),
    )
)

register_audit_labels(
    {
        "spent_on": _("Date"),
        "method": _("Paid from the cash desk"),
        "note": _("Note"),
        "reverses": _("Cancels"),
        "category": _("Category"),
    }
)
