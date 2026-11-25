from django.utils.translation import gettext_lazy as _

from apps.billing.services.cash import CashSource, register_cash_source
from apps.core.audit_display import register_labels as register_audit_labels
from apps.core.permissions import register_permission
from apps.core.registry import DashboardWidget, NavItem, registry
from apps.core.reports import ReportDef, register_report
from apps.core.roles import Role
from apps.core.settings_panel import register_section
from apps.core.system_settings import SettingDef, register_setting
from apps.students import services as student_services

D, A = Role.DIRECTOR, Role.BRANCH_ADMIN

for code, label, roles in (
    ("store.catalog.manage", _("Manage products and prices"), {D}),
    ("store.stock.receive", _("Record stock received"), {D, A}),
    ("store.stock.correct", _("Correct stock"), {D}),
    ("store.sell", _("Sell items and give books"), {D, A}),
    ("store.sale.reverse", _("Cancel sales"), {D}),
    ("store.view", _("See stock and sales"), {D, A}),
    ("store.cost.view", _("See purchase cost and margin"), {D}),
):
    register_permission(code, label, roles)

for item in (
    NavItem(
        key="store_sell",
        label=_("Sales"),
        url_name="store:sell",
        icon="tag",
        permission="store.sell",
        order=33,
        mobile_priority=42,
        active_prefix="/savdo/",
        role_priority={A: 16},
    ),
    NavItem(
        key="store_stock",
        label=_("Stock"),
        url_name="store:stock",
        icon="list",
        permission="store.view",
        order=34,
        mobile_priority=43,
        active_prefix="/ombor/",
    ),
):
    registry.add_nav(item)

register_setting(
    SettingDef(
        key="store.book_due_days",
        label=_("Book payment deadline (days)"),
        help_text=_("A book given without payment is due this many days after it was given."),
        default=7,
        min_value=0,
        max_value=90,
        order=80,
    )
)

register_audit_labels(
    {
        "low_stock_threshold": _("Low-stock threshold"),
        "movement_date": _("Date"),
        "purchase_cost": _("Purchase cost"),
        "sale_line": _("Sale line"),
        "sold_on": _("Date"),
        "settlement": _("Payment"),
        "sold_by": _("Sold by"),
        "reversed_on": _("Date"),
        "lines": _("Products"),
        "on_hand": _("On hand"),
        "quantity": _("Quantity"),
        "product": _("Product"),
        "unit_price": _("Price"),
        "total": _("Amount"),
        "group": _("Group"),
    }
)


def _cash_lines(branch_id, day):
    from . import selectors

    return selectors.cash_lines(branch_id, day)


def _cash_days(since, until):
    from . import selectors

    return selectors.cash_active_days(since, until)


register_cash_source(
    CashSource(code="store", label=_("Sales"), lines=_cash_lines, active_days=_cash_days)
)


def _books_panel(request, student):
    from apps.core.permissions import has_perm

    from . import selectors

    return {
        "student": student,
        "books": selectors.student_books(request.user, student),
        "can_give": has_perm(request.user, "store.sell"),
    }


def _low_stock(request):
    from . import selectors

    return {"rows": selectors.low_stock(request.user, request.branch_filter)}


def _register():
    from . import selectors
    from .sections import ProductSection

    register_section(ProductSection())
    student_services.register_profile_panel(
        student_services.ProfilePanel(
            key="store_books",
            template="store/panel_books.html",
            permission="store.view",
            context=_books_panel,
            order=20,
        )
    )
    register_report(
        ReportDef(
            "ombor-savdo",
            _("Stock and sales"),
            _("Per product: received, sold, on hand, sales amount and margin."),
            "store.view",
            selectors.stock_report,
            order=70,
            group=_("Sales"),
        )
    )
    registry.add_widget(
        DashboardWidget("store_low", "store/widgets/low_stock.html", "store.view", 4, _low_stock)
    )


_register()
