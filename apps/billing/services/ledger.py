"""Writing charges, discount lines and adjustments. Callers check permissions."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.system_settings import get_setting

from ..domain import discounts as disc
from ..models import Charge, ChargeAdjustment, ChargeDiscount, ChargeNet, DiscountAssignment
from .allocation import rebuild_for_student


def step() -> int:
    return get_setting("billing.rounding_step")


def assignments_on(enrollment_id: int, day: dt.date):
    return (
        DiscountAssignment.objects.filter(enrollment_id=enrollment_id, valid_from__lte=day)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=day))
        .select_related("discount_type")
        .order_by("id")
    )


def rules_for(assignments) -> list[disc.Rule]:
    return [disc.Rule(key=a, kind=a.discount_type.kind, value=a.value) for a in assignments]


def create_charge(
    *,
    actor,
    student_id: int,
    branch_id: int,
    kind: str,
    due_date: dt.date,
    base_amount: int,
    amount: int,
    suggested_amount: int | None,
    override_reason: str = "",
    enrollment=None,
    period_month=None,
    plan=None,
    part_no=None,
    price=None,
    description: str = "",
    import_batch=None,
    discount_lines: list[tuple[object, int]] | None = None,
    rebuild: bool = True,
) -> Charge:
    """Insert a charge with its discount lines. `discount_lines`: [(assignment, amount)];
    None means "compute from the enrollment's discounts valid on the due date"."""
    if amount < 0:
        raise ValidationError(_("The amount can't be negative."))
    if suggested_amount is not None and amount != suggested_amount and not override_reason.strip():
        raise ValidationError(_("A different amount needs a reason."))
    with transaction.atomic():
        charge = Charge.objects.create(
            student_id=student_id,
            branch_id=branch_id,
            enrollment=enrollment,
            group_id=enrollment.group_id if enrollment else None,
            course_id=enrollment.group.course_id if enrollment else None,
            kind=kind,
            period_month=period_month,
            plan=plan,
            part_no=part_no,
            due_date=due_date,
            base_amount=base_amount,
            suggested_amount=suggested_amount,
            amount=amount,
            override_reason=override_reason.strip(),
            price=price,
            description=description,
            import_batch=import_batch,
            created_by=actor,
        )
        if discount_lines is None and enrollment is not None:
            discount_lines = disc.lines(
                amount, rules_for(assignments_on(enrollment.pk, due_date)), step()
            )
        for assignment, value in discount_lines or []:
            if value <= 0:
                continue
            ChargeDiscount.objects.create(
                charge=charge,
                assignment=assignment,
                discount_type=assignment.discount_type,
                name_snapshot=assignment.discount_type.name,
                kind=assignment.discount_type.kind,
                value=assignment.value,
                amount=value,
            )
        audit.record(
            actor,
            "billing.charge.create",
            charge,
            after={**audit.snapshot(charge), "net": net_of(charge)},
            reason=charge.override_reason,
        )
        if rebuild:
            rebuild_for_student(student_id)
    return charge


def net_of(charge: Charge) -> int:
    return ChargeNet.objects.get(pk=charge.pk).net


def adjust(
    *,
    actor,
    charge: Charge,
    delta: int,
    kind: str,
    reason: str = "",
    suggested: int | None = None,
    rebuild: bool = True,
) -> ChargeAdjustment | None:
    """Change an issued charge's net by `delta` (append-only). Net never goes below 0."""
    if delta == 0:
        return None
    if suggested is not None and delta != suggested and not reason.strip():
        raise ValidationError(_("A different amount needs a reason."))
    with transaction.atomic():
        before = net_of(charge)
        if before + delta < 0:
            raise ValidationError(_("The charge can't go below zero."))
        adj = ChargeAdjustment.objects.create(
            charge=charge,
            amount=delta,
            kind=kind,
            suggested_amount=suggested,
            reason=reason.strip(),
            created_by=actor,
        )
        audit.record(
            actor,
            "billing.charge.adjust",
            charge,
            before={"net": before},
            after={"net": before + delta, "kind": kind},
            reason=adj.reason,
        )
        if rebuild:
            rebuild_for_student(charge.student_id)
    return adj
