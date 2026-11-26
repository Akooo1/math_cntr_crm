"""Sozlamalar sections owned by billing: prices, installment templates, discounts, methods."""

from django.db.models import Prefetch
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from apps.core import dates
from apps.core.money import format_som
from apps.core.settings_panel import Column, SettingsSection, register_section
from apps.core.system_settings import get_setting
from apps.settings.models import Course

from . import selectors, services
from .domain.installments import InvalidTemplate, build_schedule
from .forms import (
    DiscountTypeForm,
    InstallmentTemplateForm,
    PaymentMethodForm,
    PriceForm,
    format_percent_bp,
)
from .models import DiscountType, InstallmentTemplate, PaymentMethod, Price

GROUP_STUDY = _("Courses and prices")
GROUP_FINANCE = _("Finance")


def _prices_view(request, section):
    today = dates.today()
    courses = Course.objects.filter(is_active=True).prefetch_related(
        Prefetch("prices", queryset=Price.objects.select_related("branch", "group", "created_by"))
    )
    # With a branch picked in the top bar: the price in force there (its own price, or the
    # all-branches one), and only all-branches rows and that branch's rows in the history.
    branch = request.branch_filter
    rows = []
    for course in courses:
        kind = services.price_kind_for(course)
        history = [
            p
            for p in course.prices.all()
            if p.kind == kind and (branch is None or p.branch_id in (None, branch))
        ]
        current = selectors.effective_price(
            course_id=course.id, kind=kind, on_date=today, branch_id=branch
        )
        upcoming = [
            p
            for p in history
            if p.effective_from > today and p.group_id is None and (branch or not p.branch_id)
        ]
        rows.append(
            {
                "course": course,
                "current": current,
                "upcoming": upcoming,
                "history": history,
            }
        )
    return render(request, "billing/prices.html", {"section": section, "rows": rows})


class PriceSection(SettingsSection):
    """Prices are add-only: no edit, no deactivate. Each row is a point in the history."""

    slug = "narxlar"
    title = _("Prices")
    description = _("Monthly fees and full course prices with effective dates and history.")
    icon = "tag"
    order = 31
    group = GROUP_STUDY
    model = Price
    custom_view = staticmethod(_prices_view)
    form_template = "billing/price_form.html"
    allow_edit = False
    allow_toggle_active = False

    def get_form(self, request, instance=None, data=None):
        initial = {"effective_from": dates.today()}
        if request.GET.get("kurs"):
            initial["course"] = request.GET["kurs"]
        return PriceForm(data=data, initial=initial)

    def save(self, request, form):
        d = form.cleaned_data
        return services.add_price(
            actor=request.user,
            course=d["course"],
            branch=d["branch"],
            amount=d["amount"],
            effective_from=d["effective_from"],
            note=d["note"],
            group=d["group"],
        )

    def extra_context(self, request, obj):
        return {"today": dates.today()}


def _template_preview(template):
    if template is None or template.pk is None:
        return None
    try:
        parts = build_schedule(
            selectors.rule_for(template),
            total=3_000_000,
            start=dates.today(),
            step=get_setting("billing.rounding_step"),
        )
    except InvalidTemplate:
        return None
    return {"total": 3_000_000, "start": dates.today(), "parts": parts}


class InstallmentTemplateSection(SettingsSection):
    slug = "bolib-tolash"
    title = _("Installment templates")
    description = _("Number of parts and due-date rules for installment courses.")
    icon = "calendar"
    order = 32
    group = GROUP_STUDY
    model = InstallmentTemplate
    form_class = InstallmentTemplateForm
    audit_prefix = "billing.installment_template"
    form_template = "billing/installment_template_form.html"
    columns = [
        Column(_("Name"), lambda t: t.name, primary=True),
        Column(_("Course"), lambda t: t.course or _("All installment courses")),
        Column(_("Number of parts"), lambda t: t.parts_count),
        Column(_("First part due"), lambda t: t.get_first_due_display()),
    ]

    def get_queryset(self, request):
        return InstallmentTemplate.objects.select_related("course").prefetch_related("parts")

    def save(self, request, form):
        return services.save_installment_template(actor=request.user, form=form)

    def extra_context(self, request, obj):
        return {"preview": _template_preview(obj)}


def _discount_value(d: DiscountType) -> str:
    if d.kind == DiscountType.Kind.PERCENT:
        return f"{format_percent_bp(d.value)}%"
    return format_som(d.value)


class DiscountTypeSection(SettingsSection):
    slug = "chegirmalar"
    title = _("Discount types")
    description = _("Percent or fixed discounts, e.g. siblings or promo.")
    icon = "percent"
    order = 41
    group = GROUP_FINANCE
    model = DiscountType
    form_class = DiscountTypeForm
    audit_prefix = "billing.discount_type"
    columns = [
        Column(_("Name"), lambda d: d.name, primary=True),
        Column(_("Value"), _discount_value),
        Column(_("Applies to"), lambda d: d.get_applies_to_display()),
        Column(_("Director may enter a custom value"), lambda d: d.allow_custom_value, kind="bool"),
    ]


class PaymentMethodSection(SettingsSection):
    slug = "tolov-usullari"
    title = _("Payment methods")
    description = _("Cash, card terminal, bank transfer. Online methods come later.")
    icon = "card"
    order = 42
    group = GROUP_FINANCE
    model = PaymentMethod
    form_class = PaymentMethodForm
    audit_prefix = "billing.payment_method"
    columns = [
        Column(_("Name"), lambda m: m.name, primary=True),
        Column(
            _("Counted in the daily cash report"), lambda m: m.included_in_cash_close, kind="bool"
        ),
        Column(_("Order"), lambda m: m.sort_order),
    ]

    def can_edit(self, request, obj):
        return not obj.is_system

    def can_toggle(self, request, obj):
        return not obj.is_system


for section in (
    PriceSection(),
    InstallmentTemplateSection(),
    DiscountTypeSection(),
    PaymentMethodSection(),
):
    register_section(section)
