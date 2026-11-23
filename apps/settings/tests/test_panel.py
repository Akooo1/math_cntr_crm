import pytest
from django.contrib.auth import get_user_model

from apps.core.models import AuditLog
from apps.core.roles import Role
from apps.core.system_settings import get_setting
from apps.settings.models import Branch, Course, Room
from tests.factories import page_text


@pytest.mark.django_db
class TestGenericSections:
    def test_create_branch_is_audited(self, login, director):
        c = login(director)
        resp = c.post(
            "/sozlamalar/filiallar/yangi/",
            {
                "name": "Sergeli filiali",
                "address": "Sergeli",
                "phone": "71 200 03 03",
                "receipt_prefix": "se",
            },
        )
        assert resp.status_code == 302
        branch = Branch.objects.get(name="Sergeli filiali")
        assert branch.receipt_prefix == "SE"
        assert branch.phone == "+998712000303"
        entry = AuditLog.objects.get(action="settings.branch.create")
        assert entry.after["name"] == "Sergeli filiali" and entry.before is None

    def test_edit_records_before_and_after(self, login, director, branch_a):
        c = login(director)
        c.post(
            f"/sozlamalar/filiallar/{branch_a.pk}/",
            {"name": branch_a.name, "address": "Yangi manzil", "phone": "", "receipt_prefix": "CH"},
        )
        entry = AuditLog.objects.get(action="settings.branch.update")
        assert entry.before == {"address": "Toshkent"}
        assert entry.after == {"address": "Yangi manzil"}

    def test_deactivate_and_list_filter(self, login, director, branch_a):
        room = Room.objects.create(branch=branch_a, name="1-xona", capacity=10)
        c = login(director)
        assert c.post(f"/sozlamalar/xonalar/{room.pk}/holat/").status_code == 302
        room.refresh_from_db()
        assert not room.is_active
        assert "1-xona" not in page_text(c.get("/sozlamalar/xonalar/"))
        assert "1-xona" in c.get("/sozlamalar/xonalar/?nofaol=1").content.decode()
        assert AuditLog.objects.filter(action="settings.room.deactivate").exists()

    def test_validation_errors_are_uzbek(self, login, director):
        c = login(director)
        resp = c.post("/sozlamalar/kurslar/yangi/", {"name": "", "pricing_model": "monthly"})
        assert "Ushbu maydon to'ldirilishi shart." in page_text(resp)
        assert Course.objects.count() == 0

    def test_system_stage_cannot_be_deactivated(self, login, director):
        from apps.crm.models import LeadStage

        stage = LeadStage.objects.get(kind="new")
        c = login(director)
        assert c.post(f"/sozlamalar/lid-bosqichlari/{stage.pk}/holat/").status_code == 403

    def test_new_stage_is_custom_kind(self, login, director):
        from apps.crm.models import LeadStage

        c = login(director)
        c.post(
            "/sozlamalar/lid-bosqichlari/yangi/",
            {"name": "Qayta qo'ng'iroq", "color": "sky", "sort_order": 25},
        )
        assert LeadStage.objects.get(name="Qayta qo'ng'iroq").kind == "custom"

    def test_opening_balance_method_is_locked(self, login, director):
        from apps.billing.models import PaymentMethod

        system = PaymentMethod.objects.get(provider_code="opening_balance")
        c = login(director)
        assert c.get(f"/sozlamalar/tolov-usullari/{system.pk}/").status_code == 403
        assert c.post(f"/sozlamalar/tolov-usullari/{system.pk}/holat/").status_code == 403


@pytest.mark.django_db
class TestUsers:
    def test_create_user_with_branches(self, login, director, branch_a):
        c = login(director)
        resp = c.post(
            "/sozlamalar/foydalanuvchilar/yangi/",
            {
                "full_name": "Yangi Admin",
                "phone": "+998 93 111 22 33",
                "role": Role.BRANCH_ADMIN,
                "branches": [branch_a.pk],
                "password": "vaqtincha-1",
            },
        )
        assert resp.status_code == 302
        user = get_user_model().objects.get(phone="+998931112233")
        assert user.branch_ids == [branch_a.pk]
        assert user.must_change_password
        entry = AuditLog.objects.get(action="accounts.user.create")
        assert entry.after["branches"] == [branch_a.pk]
        assert "password" not in entry.after

    def test_non_director_needs_a_branch(self, login, director):
        c = login(director)
        resp = c.post(
            "/sozlamalar/foydalanuvchilar/yangi/",
            {
                "full_name": "X",
                "phone": "+998931112234",
                "role": Role.TEACHER,
                "password": "vaqtincha-1",
            },
        )
        assert resp.status_code == 200
        assert "Kamida bitta filialni tanlang." in page_text(resp)

    def test_cannot_deactivate_self(self, login, director):
        c = login(director)
        assert c.post(f"/sozlamalar/foydalanuvchilar/{director.pk}/holat/").status_code == 403
        director.refresh_from_db()
        assert director.is_active

    def test_reset_password_forces_change(self, login, director, admin_a):
        c = login(director)
        c.post(f"/sozlamalar/foydalanuvchilar/{admin_a.pk}/parol/", {"password": "boshqa-parol-1"})
        admin_a.refresh_from_db()
        assert admin_a.check_password("boshqa-parol-1") and admin_a.must_change_password
        assert AuditLog.objects.filter(action="accounts.user.password_reset").exists()

    def test_role_change_updates_access(self, login, director, admin_a, branch_a):
        c = login(director)
        c.post(
            f"/sozlamalar/foydalanuvchilar/{admin_a.pk}/",
            {
                "full_name": admin_a.full_name,
                "phone": admin_a.phone,
                "role": Role.TEACHER,
                "branches": [branch_a.pk],
            },
        )
        admin_a.refresh_from_db()
        assert admin_a.role == Role.TEACHER
        entry = AuditLog.objects.get(action="accounts.user.update")
        assert entry.before == {"role": "branch_admin"} and entry.after == {"role": "teacher"}


@pytest.mark.django_db
def test_system_settings_saved_and_audited(login, director):
    c = login(director)
    from apps.core.system_settings import all_values

    # Every registered setting is on the form; post the current values plus two changes.
    data = {key.replace(".", "__"): str(v) for key, v in all_values().items()}
    data.update({"billing__rounding_step": "100", "billing__monthly_due_day": "5"})
    resp = c.post("/sozlamalar/umumiy/", data)
    assert resp.status_code == 302
    assert get_setting("billing.rounding_step") == 100
    assert get_setting("billing.monthly_due_day") == 5
    changed = set(
        AuditLog.objects.filter(action="core.system_setting.update").values_list(
            "entity_id", flat=True
        )
    )
    assert changed == {"billing.rounding_step", "billing.monthly_due_day"}


@pytest.mark.django_db
def test_system_settings_rejects_out_of_range(login, director):
    c = login(director)
    resp = c.post(
        "/sozlamalar/umumiy/",
        {
            "billing__rounding_step": "7",
            "billing__monthly_due_day": "31",
            "billing__backdate_days": "3",
            "billing__grace_days": "0",
            "core__session_timeout_hours": "12",
        },
    )
    assert resp.status_code == 200
    assert get_setting("billing.monthly_due_day") == 10


@pytest.mark.django_db
def test_installment_template_custom_shares(login, director):
    from apps.billing.models import InstallmentTemplate

    c = login(director)
    resp = c.post(
        "/sozlamalar/bolib-tolash/yangi/",
        {
            "name": "40/30/30",
            "parts_count": 3,
            "split_mode": "custom",
            "first_due": "on_start",
            "interval_months": 1,
            "shares": "40, 30, 30",
        },
    )
    assert resp.status_code == 302
    assert InstallmentTemplate.objects.get(name="40/30/30").shares_bp() == [4000, 3000, 3000]
    bad = c.post(
        "/sozlamalar/bolib-tolash/yangi/",
        {
            "name": "xato",
            "parts_count": 3,
            "split_mode": "custom",
            "first_due": "on_start",
            "interval_months": 1,
            "shares": "50, 30, 30",
        },
    )
    assert bad.status_code == 200 and not InstallmentTemplate.objects.filter(name="xato").exists()


@pytest.mark.django_db
def test_discount_percent_parsing(login, director):
    from apps.billing.models import DiscountType

    c = login(director)
    c.post(
        "/sozlamalar/chegirmalar/yangi/",
        {"name": "Aka-uka", "kind": "percent", "value_text": "12,5", "applies_to": "any"},
    )
    assert DiscountType.objects.get(name="Aka-uka").value == 1250
    c.post(
        "/sozlamalar/chegirmalar/yangi/",
        {"name": "Promo", "kind": "fixed", "value_text": "50 000", "applies_to": "monthly"},
    )
    assert DiscountType.objects.get(name="Promo").value == 50_000
