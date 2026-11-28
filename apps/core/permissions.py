"""Permission registry and branch scoping (docs/SPEC.md 4.5).

Permissions are named codes with the roles that hold them. Modules declare theirs in
AppConfig.ready() via `register_permission`. Checks run in services and selectors, not
only in views.
"""

from dataclasses import dataclass
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import Http404

from .roles import Role


@dataclass(frozen=True)
class Permission:
    code: str
    label: str
    roles: frozenset[str]
    # The Direktor may give it to individual people (Sozlamalar -> Foydalanuvchilar).
    grantable: bool = False
    # Only the owner (Ega, a Direktor marked as owner) has it; while nobody is the owner
    # yet, every Direktor has it (docs/SPEC.md §24).
    owner_only: bool = False


_registry: dict[str, Permission] = {}


def register_permission(
    code: str, label, roles, *, grantable: bool = False, owner_only: bool = False
) -> Permission:
    perm = Permission(
        code=code,
        label=label,
        roles=frozenset(roles),
        grantable=grantable,
        owner_only=owner_only,
    )
    _registry[code] = perm
    return perm


def grantable_permissions() -> list[Permission]:
    return [p for p in all_permissions() if p.grantable]


def get_permission(code: str) -> Permission:
    try:
        return _registry[code]
    except KeyError as exc:  # a typo must fail loudly, never grant access
        raise LookupError(f"Unknown permission code: {code}") from exc


def all_permissions() -> list[Permission]:
    return sorted(_registry.values(), key=lambda p: p.code)


def has_perm(user, code: str) -> bool:
    if user is None or not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    perm = get_permission(code)
    if perm.owner_only:
        return is_director(user) and (getattr(user, "is_owner", False) or not owner_exists())
    if user.role in perm.roles:
        return True
    # Given to this person by the Direktor (only grantable permissions count).
    return perm.grantable and code in getattr(user, "granted_permissions", ())


def require_perm(user, code: str) -> None:
    if not has_perm(user, code):
        raise PermissionDenied(code)


def is_director(user) -> bool:
    return getattr(user, "role", None) == Role.DIRECTOR


def owner_exists() -> bool:
    """Is any active account the owner (Ega)? Until one is, Direktors act as owners."""
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(is_owner=True, is_active=True).exists()


# --- Branch scoping ---------------------------------------------------------------


def accessible_branch_ids(user) -> set[int] | None:
    """None means every branch (Direktor). Otherwise the set of the user's branch ids."""
    if is_director(user):
        return None
    return set(user.branch_ids)


def can_access_branch(user, branch_id: int | None) -> bool:
    ids = accessible_branch_ids(user)
    return ids is None or branch_id in ids


def ensure_branch_access(user, branch_id: int | None) -> None:
    """Objects outside the user's scope look like they don't exist (404, not 403)."""
    if not can_access_branch(user, branch_id):
        raise Http404


def scope_by_branch(qs: QuerySet, user, field: str = "branch") -> QuerySet:
    ids = accessible_branch_ids(user)
    if ids is None:
        return qs
    return qs.filter(**{f"{field}__in": ids})


def apply_branch_filter(qs: QuerySet, branch_filter: int | None, field: str = "branch"):
    """Narrow an already-scoped queryset to the branch picked in the branch switcher."""
    if branch_filter is None:
        return qs
    return qs.filter(**{f"{field}": branch_filter})


# --- View decorators ----------------------------------------------------------------


def perm_required(code: str):
    """Login + permission check for function views. Unknown codes fail at import time."""
    get_permission(code)

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            require_perm(request.user, code)
            return view(request, *args, **kwargs)

        wrapper.required_permission = code
        return wrapper

    return decorator


def login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        return view(request, *args, **kwargs)

    return wrapper
