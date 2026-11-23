"""Notification queue housekeeping (docs/SPEC.md §14). The owner keeps old records and may
delete them by hand; nothing deletes them automatically."""

import datetime as dt

from django.db import transaction
from django.db.models import Min

from . import audit, dates
from .models import OutboxEvent
from .permissions import require_perm

AGE_CHOICES = (30, 90, 180, 365)


def stats() -> dict:
    qs = OutboxEvent.objects.all()
    return {
        "total": qs.count(),
        "pending": qs.filter(processed_at__isnull=True).count(),
        "oldest": qs.aggregate(m=Min("occurred_at"))["m"],
        "by_age": {
            days: qs.filter(occurred_at__lt=dates.now() - dt.timedelta(days=days)).count()
            for days in AGE_CHOICES
        },
    }


def purge(*, actor, older_than_days: int) -> int:
    """Delete notification records older than N days. Direktor only; audited."""
    require_perm(actor, "settings.manage")
    if older_than_days not in AGE_CHOICES:
        raise ValueError(older_than_days)
    cutoff = dates.now() - dt.timedelta(days=older_than_days)
    with transaction.atomic():
        deleted, _detail = OutboxEvent.objects.filter(occurred_at__lt=cutoff).delete()
        audit.record(
            actor,
            "core.outbox.purge",
            entity_type="core.outboxevent",
            entity_id="",
            after={"older_than_days": older_than_days, "deleted": deleted},
        )
    return deleted
