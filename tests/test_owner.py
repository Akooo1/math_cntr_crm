"""The owner (Ega) above Direktors (owner's request, docs/SPEC.md §24)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts import services
from apps.core.models import AuditLog
from apps.core.permissions import has_perm
from apps.core.roles import Role
from tests.factories import UserFactory, page_text

pytestmark = pytest.mark.django_db


def fresh(u):
    return type(u).objects.get(pk=u.pk)


def test_until_someone_is_owner_directors_manage_users(director, login):
    assert has_perm(director, "accounts.users.manage")
    assert login(director).get("/sozlamalar/foydalanuvchilar/").status_code == 200


def test_a_director_makes_themselves_owner_then_others_lose_user_management(
    director, login, admin_a
):
    second = UserFactory(role=Role.DIRECTOR, full_name="Ikkinchi Direktor")
    c = login(director)
    page = c.get("/sozlamalar/foydalanuvchilar/").content.decode()
    assert f"/foydalanuvchilar/{director.pk}/ega/" in page  # "make me the owner"
    assert f"/foydalanuvchilar/{second.pk}/ega/" not in page  # not someone else
    c.post(f"/sozlamalar/foydalanuvchilar/{director.pk}/ega/")
    assert fresh(director).is_owner
    assert AuditLog.objects.filter(action="accounts.user.owner").exists()

    second = fresh(second)
    assert not has_perm(second, "accounts.users.manage")
    assert has_perm(second, "settings.manage")  # keeps everything else
    s = login(second)
    assert s.get("/sozlamalar/foydalanuvchilar/").status_code == 403
    assert s.get("/sozlamalar/").status_code == 200
    with pytest.raises(PermissionDenied):
        services.set_owner(actor=second, user=second, owner=True)
    with pytest.raises(PermissionDenied):
        services.reset_password(actor=second, user=admin_a, new_password="yangiParol123")

    owner = fresh(director)
    assert has_perm(owner, "accounts.users.manage")
    assert "Ega" in page_text(login(owner).get("/sozlamalar/foydalanuvchilar/"))


def test_owner_hands_over_but_never_leaves_nobody(director):
    services.set_owner(actor=director, user=director, owner=True)
    director = fresh(director)
    with pytest.raises(ValidationError):
        services.set_owner(actor=director, user=director, owner=False)  # the last owner
    other = UserFactory(role=Role.DIRECTOR)
    services.set_owner(actor=director, user=other, owner=True)
    services.set_owner(actor=director, user=director, owner=False)
    assert fresh(other).is_owner and not fresh(director).is_owner
    with pytest.raises(ValidationError):
        services.set_owner(actor=fresh(other), user=UserFactory(role=Role.TEACHER), owner=True)
