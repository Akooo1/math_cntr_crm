import pytest
from django.urls import reverse

from apps.core.models import AuditLog
from tests.factories import PASSWORD, UserFactory, page_text

LOGIN = "/kirish/"


@pytest.mark.django_db
class TestLogin:
    def test_login_with_any_phone_format(self, client, admin_a):
        local = admin_a.phone[4:]  # 9 digits without +998
        resp = client.post(
            LOGIN,
            {"phone": f"{local[:2]} {local[2:5]} {local[5:7]} {local[7:]}", "password": PASSWORD},
        )
        assert resp.status_code == 302 and resp["Location"] == "/"
        assert AuditLog.objects.filter(action="accounts.user.login", actor=admin_a).exists()

    def test_wrong_password_shows_uzbek_error_and_is_audited(self, client, admin_a):
        resp = client.post(LOGIN, {"phone": admin_a.phone, "password": "xato-parol"})
        assert resp.status_code == 200
        assert "Telefon raqami yoki parol noto'g'ri." in page_text(resp)
        assert AuditLog.objects.filter(action="accounts.user.login_failed").count() == 1

    def test_inactive_user_cannot_log_in(self, client, admin_a):
        admin_a.is_active = False
        admin_a.save()
        resp = client.post(LOGIN, {"phone": admin_a.phone, "password": PASSWORD})
        assert resp.status_code == 200

    def test_rate_limit_blocks_after_ten_failures(self, client, admin_a):
        for _ in range(10):
            client.post(LOGIN, {"phone": admin_a.phone, "password": "xato-parol"})
        resp = client.post(LOGIN, {"phone": admin_a.phone, "password": PASSWORD})
        assert resp.status_code == 200
        assert "Juda ko'p noto'g'ri urinish" in page_text(resp)

    def test_open_redirect_is_blocked(self, client, admin_a):
        resp = client.post(
            LOGIN + "?next=https://evil.example/", {"phone": admin_a.phone, "password": PASSWORD}
        )
        assert resp["Location"] == "/"

    def test_pages_require_login(self, client):
        resp = client.get("/sozlamalar/")
        assert resp.status_code == 302 and resp["Location"].startswith(LOGIN)

    def test_logout_is_post_only(self, login, admin_a):
        c = login(admin_a)
        assert c.get("/chiqish/").status_code == 405
        assert c.post("/chiqish/").status_code == 302
        assert c.get("/").status_code == 302


@pytest.mark.django_db
class TestPasswordChange:
    def test_forced_change_redirects_everything(self, login, branch_a):
        user = UserFactory(must_change_password=True, branches=[branch_a])
        c = login(user)
        resp = c.get("/")
        assert resp.status_code == 302 and resp["Location"] == reverse("accounts:password_change")

    def test_change_password_clears_flag(self, login, branch_a):
        user = UserFactory(must_change_password=True, branches=[branch_a])
        c = login(user)
        resp = c.post(
            reverse("accounts:password_change"),
            {
                "old_password": PASSWORD,
                "new_password1": "yangi-parol-1",
                "new_password2": "yangi-parol-1",
            },
        )
        assert resp.status_code == 302
        user.refresh_from_db()
        assert not user.must_change_password
        assert user.check_password("yangi-parol-1")
        assert c.get("/").status_code == 200  # still logged in

    @pytest.mark.parametrize("new", ["qisqa1", "12345678901"])
    def test_weak_passwords_rejected(self, login, admin_a, new):
        c = login(admin_a)
        resp = c.post(
            reverse("accounts:password_change"),
            {"old_password": PASSWORD, "new_password1": new, "new_password2": new},
        )
        assert resp.status_code == 200
        admin_a.refresh_from_db()
        assert admin_a.check_password(PASSWORD)
