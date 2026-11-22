"""Writes owned by the settings module. Everything is audited."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts import services as account_services
from apps.core import audit
from apps.core.permissions import require_perm
from apps.core.roles import Role

from .models import BranchReceiptInfo, CenterInfo, UserBranch


def _set_branches(user, branches) -> list[int]:
    ids = sorted({b.pk for b in branches}) if user.role != Role.DIRECTOR else []
    UserBranch.objects.filter(user=user).exclude(branch_id__in=ids).delete()
    existing = set(UserBranch.objects.filter(user=user).values_list("branch_id", flat=True))
    UserBranch.objects.bulk_create(
        [UserBranch(user=user, branch_id=i) for i in ids if i not in existing]
    )
    user.clear_branch_cache()
    return ids


def save_staff_user(*, actor, form, instance=None):
    require_perm(actor, "settings.manage")
    data = form.cleaned_data
    with transaction.atomic():
        if instance is None:
            user = account_services.create_user(
                actor=actor,
                phone=data["phone"],
                full_name=data["full_name"],
                role=data["role"],
                password=data["password"],
            )
            ids = _set_branches(user, data["branches"])
            audit.record(
                actor, "accounts.user.create", user, after=account_services.snapshot(user, ids)
            )
            return user
        if instance.pk == actor.pk and data["role"] != instance.role:
            raise ValidationError(_("You can't change your own role."))
        before = account_services.snapshot(instance, instance.branch_ids)
        user = account_services.update_user(
            actor=actor,
            user=instance,
            full_name=data["full_name"],
            phone=data["phone"],
            role=data["role"],
        )
        ids = _set_branches(user, data["branches"])
        audit.record(
            actor,
            "accounts.user.update",
            user,
            before=before,
            after=account_services.snapshot(user, ids),
        )
        return user


def set_user_active(*, actor, user, active: bool):
    require_perm(actor, "settings.manage")
    if user.pk == actor.pk:
        raise ValidationError(_("You can't deactivate yourself."))
    with transaction.atomic():
        before = account_services.snapshot(user)
        user.is_active = active
        user.save(update_fields=["is_active"])
        audit.record(
            actor,
            f"accounts.user.{'activate' if active else 'deactivate'}",
            user,
            before=before,
            after=account_services.snapshot(user),
        )


def save_center_info(*, actor, form) -> CenterInfo:
    require_perm(actor, "settings.manage")
    with transaction.atomic():
        existing = CenterInfo.objects.select_for_update().first()
        before = audit.snapshot(existing) if existing else None
        info = form.save(commit=False)
        if existing is not None:
            info.pk = existing.pk
        info.save()
        audit.record(
            actor,
            f"settings.center_info.{'update' if before else 'create'}",
            info,
            before=before,
            after=audit.snapshot(info),
        )
    return info


def save_branch_receipt_info(*, actor, form, branch) -> BranchReceiptInfo:
    require_perm(actor, "settings.manage")
    with transaction.atomic():
        existing = BranchReceiptInfo.objects.select_for_update().filter(branch=branch).first()
        before = audit.snapshot(existing) if existing else None
        info = form.save(commit=False)
        info.branch = branch
        if existing is not None:
            info.pk = existing.pk
        info.save()
        audit.record(
            actor,
            f"settings.branch_receipt_info.{'update' if before else 'create'}",
            info,
            before=before,
            after=audit.snapshot(info),
        )
    return info
