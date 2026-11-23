"""FIFO allocation cache. The only writer of billing_allocation (CLAUDE.md money rules)."""

from django.db import transaction

from apps.students.models import Student

from ..domain.allocation import Money, OpenCharge, allocate
from ..models import Allocation, Charge, ChargeNet, Payment


def rebuild_for_student(student_id: int) -> int:
    """Recompute who-paid-what for one student under a row lock. Returns credit left."""
    with transaction.atomic():
        Student.objects.select_for_update().filter(pk=student_id).first()
        created = dict(Charge.objects.filter(student_id=student_id).values_list("id", "created_at"))
        charges = [
            OpenCharge(
                id=n.charge_id,
                due_date=n.due_date,
                order=(created[n.charge_id], n.charge_id),
                net=n.net,
            )
            for n in ChargeNet.objects.filter(student_id=student_id, net__gt=0)
        ]
        confirmed = Payment.objects.filter(student_id=student_id, status=Payment.Status.CONFIRMED)
        reversed_ids = set(
            confirmed.filter(kind=Payment.Kind.REVERSAL).values_list("reverses_id", flat=True)
        )
        payments = [
            Money(id=p.pk, paid_on=p.paid_on, order=(p.created_at, p.pk), amount=p.amount)
            for p in confirmed.filter(kind=Payment.Kind.PAYMENT).exclude(pk__in=reversed_ids)
        ]
        refunded = sum(confirmed.filter(kind=Payment.Kind.REFUND).values_list("amount", flat=True))
        rows, credit = allocate(charges, payments, refunded)
        Allocation.objects.filter(charge__student_id=student_id).delete()
        Allocation.objects.bulk_create(
            Allocation(payment_id=p, charge_id=c, amount=a) for p, c, a in rows
        )
    return credit
