import pytest

from apps.core.roles import Role
from tests.factories import BranchFactory, UserFactory


@pytest.fixture
def branch_a(db):
    return BranchFactory(name="Chilonzor filiali", receipt_prefix="CH")


@pytest.fixture
def branch_b(db):
    return BranchFactory(name="Yunusobod filiali", receipt_prefix="YU")


@pytest.fixture
def director(db):
    return UserFactory(role=Role.DIRECTOR, full_name="Direktor")


@pytest.fixture
def admin_a(branch_a):
    return UserFactory(role=Role.BRANCH_ADMIN, branches=[branch_a], full_name="Admin A")


@pytest.fixture
def manager_a(branch_a):
    return UserFactory(role=Role.SALES_MANAGER, branches=[branch_a], full_name="Menejer A")


@pytest.fixture
def teacher_a(branch_a):
    return UserFactory(role=Role.TEACHER, branches=[branch_a], full_name="O'qituvchi A")


@pytest.fixture
def users_by_role(director, admin_a, manager_a, teacher_a):
    return {
        Role.DIRECTOR: director,
        Role.BRANCH_ADMIN: admin_a,
        Role.SALES_MANAGER: manager_a,
        Role.TEACHER: teacher_a,
    }


@pytest.fixture
def login(client):
    def _login(user):
        client.force_login(user, backend="apps.accounts.backends.PhoneBackend")
        return client

    return _login
