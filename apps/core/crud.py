"""Generic audited writes for reference data edited in Sozlamalar."""

from django.db import models, transaction

from . import audit


def _fresh_snapshot(obj: models.Model, m2m: tuple[str, ...]) -> dict | None:
    """Snapshot from the database, because ModelForm.is_valid() already mutated `obj`."""
    if obj.pk is None:
        return None
    fresh = type(obj)._default_manager.get(pk=obj.pk)
    extra = {name: sorted(getattr(fresh, name).values_list("pk", flat=True)) for name in m2m}
    return audit.snapshot(fresh, extra)


def save_form(form, *, actor, action_prefix: str, m2m: tuple[str, ...] = ()) -> models.Model:
    """Save a ModelForm and write create/update audit rows in one transaction."""
    with transaction.atomic():
        before = _fresh_snapshot(form.instance, m2m)
        obj = form.save()
        extra = {name: sorted(getattr(obj, name).values_list("pk", flat=True)) for name in m2m}
        after = audit.snapshot(obj, extra)
        verb = "update" if before is not None else "create"
        audit.record(actor, f"{action_prefix}.{verb}", obj, before=before, after=after)
    return obj


def set_active(obj: models.Model, active: bool, *, actor, action_prefix: str) -> models.Model:
    with transaction.atomic():
        obj = type(obj)._default_manager.select_for_update().get(pk=obj.pk)
        if obj.is_active == active:
            return obj
        before = audit.snapshot(obj)
        obj.is_active = active
        obj.save(update_fields=["is_active"])
        audit.record(
            actor,
            f"{action_prefix}.{'activate' if active else 'deactivate'}",
            obj,
            before=before,
            after=audit.snapshot(obj),
        )
    return obj
