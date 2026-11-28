"""Writes for users. Callers check permissions; login flows are open by nature."""

from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth import login as dj_login
from django.contrib.auth import logout as dj_logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.permissions import require_perm
from apps.core.system_settings import get_setting

User = get_user_model()

AUDIT_FIELDS = ("phone", "full_name", "role", "is_active", "must_change_password")


def _snap(user, branch_ids=None):
    data = {f: getattr(user, f) for f in AUDIT_FIELDS}
    if branch_ids is not None:
        data["branches"] = sorted(branch_ids)
    return data


def log_in(request, user) -> None:
    dj_login(request, user)
    request.session.set_expiry(get_setting("core.session_timeout_hours") * 3600)
    audit.record(user, "accounts.user.login", user, only_changes=False)


def record_failed_login(phone: str) -> None:
    user = User.objects.filter(phone=phone).first()
    audit.record(
        None,
        "accounts.user.login_failed",
        entity_type="accounts.user",
        entity_id=user.pk if user else "",
        after={"phone": phone},
    )


def log_out(request) -> None:
    user = request.user
    if user.is_authenticated:
        audit.record(user, "accounts.user.logout", user, only_changes=False)
    dj_logout(request)


def change_own_password(request, new_password: str) -> None:
    user = request.user
    with transaction.atomic():
        user.set_password(new_password)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        audit.record(user, "accounts.user.password_change", user, only_changes=False)
    update_session_auth_hash(request, user)


# --- Staff management (Direktor, from Sozlamalar) ---------------------------------


def create_user(*, actor, phone, full_name, role, password) -> User:
    require_perm(actor, "settings.manage")
    user = User(phone=phone, full_name=full_name, role=role, must_change_password=True)
    validate_password(password, user)
    user.set_password(password)
    user.save()
    return user


def update_user(*, actor, user: User, full_name, phone, role) -> User:
    require_perm(actor, "settings.manage")
    user.full_name = full_name
    user.phone = phone
    user.role = role
    user.save(update_fields=["full_name", "phone", "role"])
    return user


def reset_password(*, actor, user: User, new_password: str) -> None:
    require_perm(actor, "accounts.users.manage")
    validate_password(new_password, user)
    with transaction.atomic():
        user.set_password(new_password)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        audit.record(actor, "accounts.user.password_reset", user, only_changes=False)


def set_owner(*, actor, user: User, owner: bool) -> User:
    """Make a Direktor the owner (Ega), or take it back (SPEC §24). The owner does it; while
    nobody is the owner, a Direktor may make themselves the owner. The last owner can't
    stop being one (someone must manage users)."""
    from apps.core.permissions import owner_exists

    if not actor.is_director:
        raise PermissionDenied
    if owner_exists():
        if not actor.is_owner:
            raise PermissionDenied
    elif not (owner and user.pk == actor.pk):
        raise PermissionDenied
    if owner and (not user.is_director or not user.is_active):
        raise ValidationError(_("Only an active Direktor can be the owner."))
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if user.is_owner == owner:
            return user
        if (
            not owner
            and not User.objects.filter(is_owner=True, is_active=True).exclude(pk=user.pk).exists()
        ):
            raise ValidationError(_("Make someone else the owner first."))
        user.is_owner = owner
        user.save(update_fields=["is_owner"])
        audit.record(
            actor,
            "accounts.user.owner",
            user,
            before={"is_owner": not owner},
            after={"is_owner": owner},
        )
    return user


def snapshot(user, branch_ids=None) -> dict:
    return _snap(user, branch_ids)
