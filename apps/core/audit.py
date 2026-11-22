"""Audit log writer. Call only from services, inside the same transaction as the change."""

import datetime as dt
from typing import Any

from django.db import models

from .models import AuditLog
from .request_context import get_request_info


def _serialize(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dt.time):
        return value.strftime("%H:%M")
    if isinstance(value, (list, tuple, set)):
        return [_serialize(v) for v in value]
    if hasattr(value, "pk"):
        return value.pk
    return value


SKIP_FIELDS = {"password", "created_at", "updated_at", "last_login"}


def snapshot(obj: models.Model | None, extra: dict | None = None) -> dict | None:
    """Plain-JSON snapshot of the model's concrete fields (FKs as ids)."""
    if obj is None:
        return None
    data = {}
    for field in obj._meta.concrete_fields:
        if field.primary_key or field.name in SKIP_FIELDS:
            continue
        data[field.name] = _serialize(getattr(obj, field.attname))
    if extra:
        data.update({k: _serialize(v) for k, v in extra.items()})
    return data


def diff(before: dict | None, after: dict | None) -> tuple[dict | None, dict | None]:
    """Keep only keys whose values changed. Returns (before, after) reduced."""
    if before is None or after is None:
        return before, after
    keys = [k for k in after if before.get(k) != after.get(k)]
    keys += [k for k in before if k not in after]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def entity_type_of(obj: models.Model) -> str:
    return obj._meta.label_lower


def record(
    actor,
    action: str,
    obj: models.Model | None = None,
    *,
    before: dict | None = None,
    after: dict | None = None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    branch_id: int | None = None,
    reason: str = "",
    only_changes: bool = True,
) -> AuditLog | None:
    """Write one audit row. With only_changes, an update that changed nothing is skipped."""
    if only_changes and before is not None and after is not None:
        before, after = diff(before, after)
        if not after and not before:
            return None
    if obj is not None:
        entity_type = entity_type or entity_type_of(obj)
        entity_id = entity_id if entity_id is not None else obj.pk
        if branch_id is None:
            branch_id = getattr(obj, "branch_id", None)
    info = get_request_info()
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        entity_type=entity_type or "",
        entity_id="" if entity_id is None else str(entity_id),
        branch_id=branch_id,
        before=before,
        after=after,
        reason=reason or "",
        ip=info.ip,
        user_agent=(info.user_agent or "")[:300],
    )
