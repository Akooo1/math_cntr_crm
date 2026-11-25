import dataclasses

from apps.core.events import DomainEvent


@dataclasses.dataclass(frozen=True)
class SaleRecorded(DomainEvent):
    """A counter sale or a book given (paid now or on account)."""

    name = "store.sale_recorded"

    sale_id: int
    branch_id: int
    total: int


@dataclasses.dataclass(frozen=True)
class SaleReversed(DomainEvent):
    name = "store.sale_reversed"

    sale_id: int
    reversal_id: int
