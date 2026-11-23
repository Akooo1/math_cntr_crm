import dataclasses

from apps.core.events import DomainEvent


@dataclasses.dataclass(frozen=True)
class PaymentRecorded(DomainEvent):
    """A future Telegram module can send the receipt to the parent from this."""

    name = "billing.payment_recorded"

    payment_id: int
    student_id: int
    branch_id: int
    amount: int


@dataclasses.dataclass(frozen=True)
class PaymentReversed(DomainEvent):
    name = "billing.payment_reversed"

    payment_id: int
    reversal_id: int


@dataclasses.dataclass(frozen=True)
class RefundIssued(DomainEvent):
    name = "billing.refund_issued"

    payment_id: int
    student_id: int
    amount: int
