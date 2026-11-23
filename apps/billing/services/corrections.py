"""Direktor-only corrections outside the enrollment flows (SPEC Q-14)."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.permissions import ensure_branch_access, require_perm

from ..models import Charge
from . import ledger


def correct_charge(*, actor, charge: Charge, new_net: int, reason: str):
    """Set an issued charge's net to `new_net` (0 cancels it) via an adjustment row."""
    require_perm(actor, "billing.reverse")
    ensure_branch_access(actor, charge.branch_id)
    if not reason.strip():
        raise ValidationError(_("Write the reason."))
    if new_net < 0:
        raise ValidationError(_("The amount can't be negative."))
    with transaction.atomic():
        Charge.objects.select_for_update().get(pk=charge.pk)
        current = ledger.net_of(charge)
        kind = "cancellation" if new_net == 0 else "correction"
        return ledger.adjust(
            actor=actor, charge=charge, delta=new_net - current, kind=kind, reason=reason
        )


def manual_charge(*, actor, student, amount: int, due_date: dt.date, description: str) -> Charge:
    """An extra charge (e.g. a textbook). Direktor only."""
    require_perm(actor, "billing.reverse")
    ensure_branch_access(actor, student.branch_id)
    if amount <= 0:
        raise ValidationError(_("The amount must be positive."))
    if not description.strip():
        raise ValidationError(_("Write what the charge is for."))
    return ledger.create_charge(
        actor=actor,
        student_id=student.pk,
        branch_id=student.branch_id,
        kind=Charge.Kind.MANUAL,
        due_date=due_date,
        base_amount=amount,
        amount=amount,
        suggested_amount=None,
        description=description.strip(),
        discount_lines=[],
    )
