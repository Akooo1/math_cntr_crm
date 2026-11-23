import pytest
from django.http import Http404

from apps.core import permissions
from apps.core.roles import Role
from apps.settings.models import Room


@pytest.mark.django_db
class TestScoping:
    def test_director_sees_all_branches(self, director, branch_a, branch_b):
        assert permissions.accessible_branch_ids(director) is None
        assert permissions.can_access_branch(director, branch_b.pk)

    def test_admin_limited_to_own_branch(self, admin_a, branch_a, branch_b):
        assert permissions.accessible_branch_ids(admin_a) == {branch_a.pk}
        assert not permissions.can_access_branch(admin_a, branch_b.pk)
        with pytest.raises(Http404):
            permissions.ensure_branch_access(admin_a, branch_b.pk)

    def test_scope_by_branch_filters_queryset(self, admin_a, director, branch_a, branch_b):
        Room.objects.create(branch=branch_a, name="A1", capacity=5)
        Room.objects.create(branch=branch_b, name="B1", capacity=5)
        assert [r.name for r in permissions.scope_by_branch(Room.objects.all(), admin_a)] == ["A1"]
        assert permissions.scope_by_branch(Room.objects.all(), director).count() == 2

    def test_unknown_permission_code_fails_loudly(self, director):
        with pytest.raises(LookupError):
            permissions.has_perm(director, "no.such.permission")

    def test_inactive_user_has_no_permissions(self, director):
        director.is_active = False
        assert not permissions.has_perm(director, "settings.manage")

    def test_settings_permission_is_director_only(self, users_by_role):
        for role, user in users_by_role.items():
            assert permissions.has_perm(user, "settings.manage") is (role == Role.DIRECTOR)


@pytest.mark.django_db
def test_phone_bottom_bar_depends_on_role(rf, users_by_role):
    from apps.core.context_processors import layout

    def bar(role):
        request = rf.get("/")
        request.user = users_by_role[role]
        request.branch_filter = None
        return [n["item"].key for n in layout(request)["nav_mobile"]]

    assert bar(Role.TEACHER) == ["home", "attendance", "groups", "students"]
    assert bar(Role.BRANCH_ADMIN)[:2] == ["home", "students"]
    assert bar(Role.SALES_MANAGER)[:3] == ["home", "leads", "tasks"]
