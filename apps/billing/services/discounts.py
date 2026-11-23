"""Discount assignments (SPEC 6.4.4, Q-8). They affect only charges created afterwards."""

import datetime as dt

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.permissions import ensure_branch_access, has_perm, require_perm

from ..models import DiscountAssignment, DiscountType


def assign(
    *,
    actor,
    enrollment,
    discount_type: DiscountType,
    valid_from: dt.date,
    valid_to: dt.date | None = None,
    value: int | None = None,
    reason: str = "",
) -> DiscountAssignment:
    require_perm(actor, "billing.discount.assign")
    ensure_branch_access(actor, enrollment.group.branch_id)
    if not discount_type.is_active:
        raise ValidationError(_("This discount type is not active."))
    model = "monthly" if enrollment.group.course.is_monthly else "installment"
    if discount_type.applies_to not in (model, "any"):
        raise ValidationError(_("This discount doesn't apply to this course."))
    if value is None or value == discount_type.value:
        value = discount_type.value
    else:
        if not discount_type.allow_custom_value:
            raise ValidationError(_("This discount has a fixed value."))
        if not has_perm(actor, "billing.discount.custom"):
            raise PermissionDenied
    if value <= 0 or (discount_type.kind == "percent" and value > 10_000):
        raise ValidationError(_("A percent must be above 0 and at most 100."))
    if valid_to and valid_to < valid_from:
        raise ValidationError(_("The end date must be after the start date."))
    with transaction.atomic():
        row = DiscountAssignment.objects.create(
            enrollment=enrollment,
            discount_type=discount_type,
            value=value,
            valid_from=valid_from,
            valid_to=valid_to,
            reason=reason.strip(),
            created_by=actor,
        )
        audit.record(
            actor,
            "billing.discount.assign",
            row,
            after=audit.snapshot(row),
            branch_id=enrollment.group.branch_id,
            reason=row.reason,
        )
    return row


def end(*, actor, assignment: DiscountAssignment, valid_to: dt.date) -> DiscountAssignment:
    require_perm(actor, "billing.discount.assign")
    ensure_branch_access(actor, assignment.enrollment.group.branch_id)
    if valid_to < assignment.valid_from:
        raise ValidationError(_("The end date must be after the start date."))
    with transaction.atomic():
        before = audit.snapshot(assignment)
        assignment.valid_to = valid_to
        assignment.ended_by = actor
        assignment.ended_at = timezone.now()
        assignment.save(update_fields=["valid_to", "ended_by", "ended_at"])
        audit.record(
            actor,
            "billing.discount.end",
            assignment,
            before=before,
            after=audit.snapshot(assignment),
            branch_id=assignment.enrollment.group.branch_id,
        )
    return assignment
