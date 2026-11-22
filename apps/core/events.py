"""In-process domain event bus with an outbox (docs/SPEC.md 4.4).

Handlers run synchronously inside the publisher's transaction, so a failing handler rolls
the whole change back. Events marked `outbox = True` are also stored in core_outbox_event
for asynchronous consumers (future Telegram / SMS modules).
"""

import dataclasses
from collections import defaultdict
from collections.abc import Callable
from typing import ClassVar

from .audit import _serialize
from .models import OutboxEvent


@dataclasses.dataclass(frozen=True)
class DomainEvent:
    name: ClassVar[str] = "event"
    outbox: ClassVar[bool] = True

    def payload(self) -> dict:
        return {k: _serialize(v) for k, v in dataclasses.asdict(self).items()}


_handlers: dict[str, list[Callable[[DomainEvent], None]]] = defaultdict(list)


def subscribe(event_cls: type[DomainEvent]):
    """Decorator: @subscribe(EnrollmentCreated) def handle(event): ..."""

    def decorator(func):
        if func not in _handlers[event_cls.name]:
            _handlers[event_cls.name].append(func)
        return func

    return decorator


def publish(event: DomainEvent) -> None:
    if event.outbox:
        OutboxEvent.objects.create(event_type=event.name, payload=event.payload())
    for handler in list(_handlers.get(event.name, [])):
        handler(event)


def handlers_for(event_cls: type[DomainEvent]) -> list:
    return list(_handlers.get(event_cls.name, []))
