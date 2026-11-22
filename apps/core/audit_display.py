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
}

ENTITY_FALLBACK = {"core.systemsetting": _("System setting")}


def verb_label(action: str):
    return VERBS.get(action.rsplit(".", 1)[-1], action)


def _model(entity_type: str):
    try:
        return apps.get_model(entity_type)
    except (LookupError, ValueError):
        return None


def entity_label(entity_type: str):
    model = _model(entity_type)
    if model is None:
        return ENTITY_FALLBACK.get(entity_type, entity_type)
    return model._meta.verbose_name


def _format(field: models.Field | None, value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
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
        field = None
        label = key
        if model is not None:
            try:
                field = model._meta.get_field(key)
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
