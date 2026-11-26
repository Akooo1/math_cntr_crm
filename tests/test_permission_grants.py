"""Per-person extra permissions (docs/SPEC.md §22): the Direktor gives an administrator
Ombor rights in Sozlamalar -> Foydalanuvchilar."""

import pytest

from apps.core.models import AuditLog
from apps.core.permissions import grantable_permissions, has_perm
from apps.settings.models import UserPermissionGrant
from tests.factories import page_text

pytestmark = pytest.mark.django_db


def fresh(user):
    """A new copy, as each request gets (grants are cached on the user object)."""
    return type(user).objects.get(pk=user.pk)


def edit(client, user, branch, perms):
    return client.post(
        f"/sozlamalar/foydalanuvchilar/{user.pk}/",
        {
            "full_name": user.full_name,
            "phone": user.phone,
            "role": user.role,
            "branches": [branch.pk],
            "extra_permissions": perms,
        },
    )


def test_only_store_rights_are_grantable():
    assert {p.code for p in grantable_permissions()} == {
        "store.catalog.manage",
        "store.stock.receive",
        "store.stock.correct",
    }


def test_director_gives_and_takes_back(login, director, admin_a, branch_a):
    c = login(director)
    assert not has_perm(admin_a, "store.stock.receive")
    resp = edit(c, admin_a, branch_a, ["store.stock.receive", "store.catalog.manage"])
    assert resp.status_code == 302
    admin_a = fresh(admin_a)
    assert has_perm(admin_a, "store.stock.receive") and has_perm(admin_a, "store.catalog.manage")
    assert not has_perm(admin_a, "store.stock.correct")
    log = AuditLog.objects.get(action="accounts.user.permissions")
    assert log.after["permissions"] == ["store.catalog.manage", "store.stock.receive"]

    a = login(admin_a)
    assert a.get("/ombor/kirim/").status_code == 200
    assert a.get("/sozlamalar/mahsulotlar/").status_code == 200  # only the page given
    assert a.get("/sozlamalar/foydalanuvchilar/").status_code == 403
    index = page_text(a.get("/sozlamalar/"))
    assert "Mahsulotlar" in index and "Foydalanuvchilar" not in index

    edit(login(director), admin_a, branch_a, [])
    admin_a = fresh(admin_a)
    assert not has_perm(admin_a, "store.stock.receive")
    assert not UserPermissionGrant.objects.filter(user=admin_a).exists()


def test_non_grantable_codes_are_ignored(login, director, admin_a, branch_a):
    edit(login(director), admin_a, branch_a, ["store.stock.receive"])
    UserPermissionGrant.objects.create(user=admin_a, code="billing.reverse", granted_by=director)
    admin_a = fresh(admin_a)
    assert not has_perm(admin_a, "billing.reverse")  # only grantable codes ever count


def test_without_any_page_settings_is_closed(login, admin_a):
    assert login(admin_a).get("/sozlamalar/").status_code == 403
