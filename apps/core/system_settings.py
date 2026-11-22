"""Typed system settings: defined in code, values stored in core_system_setting."""

from dataclasses import dataclass

from django.db import transaction

from . import audit
from .models import SystemSetting


@dataclass(frozen=True)
class SettingDef:
    key: str
    label: str
    default: int
    help_text: str = ""
    min_value: int | None = None
    max_value: int | None = None
    choices: tuple[tuple[int, str], ...] | None = None
    order: int = 100

    def validate(self, value: int) -> int:
        value = int(value)
        if self.choices is not None and value not in {c[0] for c in self.choices}:
            raise ValueError(value)
        if self.min_value is not None and value < self.min_value:
            raise ValueError(value)
        if self.max_value is not None and value > self.max_value:
            raise ValueError(value)
        return value


_defs: dict[str, SettingDef] = {}


def register_setting(definition: SettingDef) -> None:
    _defs[definition.key] = definition


def definitions() -> list[SettingDef]:
    return sorted(_defs.values(), key=lambda d: (d.order, d.key))


def get_def(key: str) -> SettingDef:
    return _defs[key]


def get_setting(key: str) -> int:
    definition = _defs[key]
    row = SystemSetting.objects.filter(key=key).first()
    return definition.default if row is None else row.value


def all_values() -> dict[str, int]:
    stored = dict(SystemSetting.objects.values_list("key", "value"))
    return {d.key: stored.get(d.key, d.default) for d in definitions()}


def set_settings(values: dict[str, int], *, actor) -> list[str]:
    """Validate and store several settings at once. Every change is audited."""
    changed = []
    with transaction.atomic():
        for key, raw in values.items():
            definition = _defs[key]
            value = definition.validate(raw)
            old = get_setting(key)
            if old == value:
                continue
            SystemSetting.objects.update_or_create(
                key=key, defaults={"value": value, "updated_by": actor}
            )
            audit.record(
                actor,
                "core.system_setting.update",
                entity_type="core.systemsetting",
                entity_id=key,
                before={key: old},
                after={key: value},
            )
            changed.append(key)
    return changed
