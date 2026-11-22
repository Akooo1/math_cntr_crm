import datetime as dt

from .models import InstallmentTemplate, PaymentMethod, Price


def effective_price(*, course_id: int, kind: str, on_date: dt.date, branch_id: int | None):
    """Price in force on `on_date` (SPEC 5.6): the most specific scope wins (branch, then
    all branches); within a scope the latest effective_from <= on_date, then latest created.
    """
    base = Price.objects.filter(course_id=course_id, kind=kind, effective_from__lte=on_date)
    scopes = []
    if branch_id is not None:
        scopes.append(base.filter(branch_id=branch_id))
    scopes.append(base.filter(branch__isnull=True))
    for qs in scopes:
        price = qs.order_by("-effective_from", "-created_at", "-id").first()
        if price is not None:
            return price
    return None


def price_history(course_id: int):
    return Price.objects.filter(course_id=course_id).select_related("branch", "created_by")


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


def payment_methods_for_entry():
    from .providers import selectable_providers

    codes = [p.code for p in selectable_providers()]
    return PaymentMethod.objects.filter(is_active=True, provider_code__in=codes)
