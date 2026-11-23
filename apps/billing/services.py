"""Billing writes for module 1 phase 1: price history and installment templates.

The ledger services (charges, payments, allocation, cash close) arrive in phase 4.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.permissions import require_perm
from apps.settings.models import Course

from .models import InstallmentTemplate, InstallmentTemplatePart, Price


def price_kind_for(course: Course) -> str:
    return Price.Kind.MONTHLY if course.is_monthly else Price.Kind.FULL_COURSE


def add_price(
    *, actor, course, branch, amount: int, effective_from, note: str = "", group=None
) -> Price:
    """Add a price row. Never changes earlier rows or charges already issued (SPEC 6.4.2)."""
    require_perm(actor, "settings.manage")
    if amount <= 0:
        raise ValidationError(_("The amount must be positive."))
    if group is not None:
        if group.course_id != course.pk:
            raise ValidationError(_("The group belongs to another course."))
        if branch is not None and branch.pk != group.branch_id:
            raise ValidationError(_("The group is in another branch."))
        branch = group.branch
    with transaction.atomic():
        price = Price.objects.create(
            course=course,
            branch=branch,
            group=group,
            kind=price_kind_for(course),
            amount=amount,
            effective_from=effective_from,
            note=note,
            created_by=actor,
        )
        audit.record(actor, "billing.price.create", price, after=audit.snapshot(price))
    return price


def save_installment_template(*, actor, form) -> InstallmentTemplate:
    require_perm(actor, "settings.manage")
    with transaction.atomic():
        instance = form.instance
        before = None
        if instance.pk:
            fresh = InstallmentTemplate.objects.get(pk=instance.pk)
            before = audit.snapshot(fresh, {"shares_bp": fresh.shares_bp()})
        template = form.save()
        template.parts.all().delete()
        if template.split_mode == InstallmentTemplate.SplitMode.CUSTOM:
            InstallmentTemplatePart.objects.bulk_create(
                InstallmentTemplatePart(template=template, part_no=i + 1, share_bp=bp)
                for i, bp in enumerate(form.shares_bp)
            )
        after = audit.snapshot(template, {"shares_bp": template.shares_bp()})
        audit.record(
            actor,
            f"billing.installment_template.{'update' if before else 'create'}",
            template,
            before=before,
            after=after,
        )
    return template
