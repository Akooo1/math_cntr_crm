"""Turns raw audit rows into readable Uzbek text for the audit log viewer."""

import datetime as dt

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils.translation import gettext_lazy as _

from . import dates, money

VERBS = {
    "create": _("Created"),
    "update": _("Changed"),
    "activate": _("Activated"),
    "deactivate": _("Deactivated"),
    "login": _("Logged in"),
    "login_failed": _("Failed login"),
    "logout": _("Logged out"),
    "password_change": _("Changed password"),
    "password_reset": _("Password reset"),
    "assign": _("Given"),
    "end": _("Ended"),
    "adjust": _("Amount changed"),
    "reverse": _("Payment reversed"),
    "refund": _("Money refunded"),
    "close": _("Closed"),
    "convert": _("Converted to a student"),
    "cancel": _("Cancelled"),
    "restore": _("Restored"),
    "commit": _("Imported"),
    "freeze": _("Frozen"),
    "unfreeze": _("Unfrozen"),
    "leave": _("Left the group"),
    "move": _("Moved to another group"),
    "edit": _("Changed"),
    "run": _("Done"),
}

ENTITY_FALLBACK = {
    "core.systemsetting": _("System setting"),
    "core.outboxevent": _("Notification queue"),
}

# Labels for audit keys that are not model fields, or whose field has no Uzbek label.
# Modules add their own with register_labels().
LABELS = {
    "created_by": _("Created by"),
    "created_at": _("Created at"),
    "updated_at": _("Updated at"),
    "branches": _("Branches"),
    "kind": _("Type"),
    "value": _("Value"),
    "amount": _("Amount"),
    "date": _("Date"),
    "reason": _("Reason"),
    "student": _("Student"),
    "group": _("Group"),
    "lead": _("Lead"),
    "lesson": _("Lesson"),
    "enrollment": _("Group"),
    "stage": _("Stage"),
    "user": _("User"),
    "branch": _("Branch"),
    "before": _("Before"),
    "after": _("After"),
}
# Technical keys never shown (they mean nothing to staff).
HIDDEN = {
    "provider_code",
    "external_id",
    "receipt_seq",
    "import_batch",
    "template_snapshot",
    "phone_normalized",
    "report",
    "file",
    "payload",
    "last_seq",
    "share_bp",
}


def register_labels(labels: dict) -> None:
    LABELS.update(labels)


def _is_default_label(field) -> bool:
    # Reverse relations (e.g. Month.lines) have no verbose_name: fall back to LABELS.
    if not hasattr(field, "verbose_name"):
        return True
    return str(field.verbose_name) == field.name.replace("_", " ")


def verb_label(action: str):
    return VERBS.get(action.rsplit(".", 1)[-1], _("Changed"))


def _model(entity_type: str):
    try:
        return apps.get_model(entity_type)
    except (LookupError, ValueError):
        return None


def entity_label(entity_type: str):
    if entity_type in ENTITY_FALLBACK:
        return ENTITY_FALLBACK[entity_type]
    model = _model(entity_type)
    if model is None:
        return entity_type
    return model._meta.verbose_name


def _format(field: models.Field | None, value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    if isinstance(value, dict) or (
        isinstance(value, list) and value and isinstance(value[0], dict)
    ):
        return len(value)  # structured detail (e.g. totals per method): show its size only
    if field is None:
        return value
    if getattr(field, "is_money", False):
        return money.format_som(int(value))
    if field.choices:
        return dict(field.flatchoices).get(value, value)
    if isinstance(field, models.ForeignKey):
        obj = field.related_model._default_manager.filter(pk=value).first()
        return str(obj) if obj else f"#{value}"
    if isinstance(field, models.ManyToManyField) or isinstance(value, list):
        related = getattr(field, "related_model", None)
        if related is not None:
            return ", ".join(str(o) for o in related._default_manager.filter(pk__in=value)) or "—"
        return ", ".join(str(v) for v in value)
    if isinstance(field, models.DateField) and not isinstance(field, models.DateTimeField):
        try:
            return dates.format_date(dt.date.fromisoformat(value))
        except (TypeError, ValueError):
            return value
    return value


def changes(entry) -> list[dict]:
    """[{label, before, after}] for the fields present in the entry."""
    model = _model(entry.entity_type)
    before = entry.before or {}
    after = entry.after or {}
    rows = []
    for key in list(dict.fromkeys([*before.keys(), *after.keys()])):
        if key in HIDDEN:
            continue
        field = None
        label = LABELS.get(key, key)
        if model is not None:
            try:
                field = model._meta.get_field(key)
                if not _is_default_label(field):
                    label = field.verbose_name
            except FieldDoesNotExist:
                pass
        if model is None and entry.entity_type == "core.systemsetting":
            from .system_settings import _defs

            if key in _defs:
                label = _defs[key].label
        rows.append(
            {
                "label": label,
                "before": _format(field, before.get(key)) if key in before else None,
                "after": _format(field, after.get(key)) if key in after else None,
            }
        )
    return rows


def label_for(model, key):
    """The label the audit viewer would show for `key`, or None if it is hidden/unknown."""
    if key in HIDDEN:
        return None
    try:
        field = model._meta.get_field(key)
        if not _is_default_label(field):
            return field.verbose_name
    except FieldDoesNotExist:
        pass
    return LABELS.get(key)
