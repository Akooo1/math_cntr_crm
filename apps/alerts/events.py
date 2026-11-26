from dataclasses import dataclass

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class AlertCreated(DomainEvent):
    """A warning task was made. The telegram module tells the assignee (lead deadline)."""

    name = "alerts.created"
    outbox = False
    task_id: int
    kind: str
    assigned_to_id: int | None
