"""The Direktor/admin screens end to end, and the validation branches of billing services."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.billing import services
from apps.billing.models import Charge, DiscountAssignment, InstallmentPlan, Payment
from apps.core.models import AuditLog
from apps.students import services as st
from tests.factories import make_group, make_student, page_text

from .helpers import MWF, D, fixed, net, percent

pytestmark = pytest.mark.django_db
TODAY = D(2026, 11, 16)


@pytest.fixture
def enrolled(admin_a, student, group):
    return st.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 11, 2))


def pay(actor, student, amount, method):
    return services.payments.record_payment(
        actor=actor, student=student, amount=amount, method=method, paid_on=TODAY
    )


class TestDirectorScreens:
    def test_reverse_refund_correct_and_manual_charge(
        self, login, admin_a, director, student, enrolled, cash
    ):
        p = pay(admin_a, student, 600_000, cash)
        c = login(director)
        assert (
            c.post(f"/tolovlar/{p.pk}/bekor-qilish/", {"reason": ""}).status_code == 200
        )  # reason required
        assert (
            c.post(f"/tolovlar/{p.pk}/bekor-qilish/", {"reason": "Xato summa"}).status_code == 302
        )
        assert Payment.objects.filter(kind="reversal").count() == 1
        pay(admin_a, student, 600_000, cash)
        resp = c.post(
            f"/hisob/{student.pk}/pul-qaytarish/",
            {"amount": "200 000", "method": cash.pk, "reason": "x"},
        )
        assert resp.status_code == 200 and "Faqat avansni" in page_text(resp)  # credit is 150 000
        assert (
            c.post(
                f"/hisob/{student.pk}/pul-qaytarish/",
                {"amount": "150 000", "method": cash.pk, "reason": "Ortiqcha"},
            ).status_code
            == 302
        )
        charge = Charge.objects.get(enrollment=enrolled)
        assert (
            c.post(
                f"/hisoblangan/{charge.pk}/tuzatish/", {"new_net": "400 000", "reason": "Kelishuv"}
            ).status_code
            == 302
        )
        assert net(charge) == 400_000
        assert (
            c.post(
                f"/hisob/{student.pk}/qoshimcha/",
                {"description": "Kitob", "amount": "60 000", "due_date": "20.11.2026"},
            ).status_code
            == 302
        )
        assert Charge.objects.filter(kind="manual", description="Kitob").exists()
        assert c.get(f"/hisob/{student.pk}/qoshimcha/").status_code == 200

    def test_discount_screens(self, login, admin_a, director, student, enrolled):
        dtype = percent(allow_custom_value=True)
        c = login(admin_a)
        form = {
            "enrollment": enrolled.pk,
            "discount_type": dtype.pk,
            "valid_from": "01.12.2026",
            "reason": "aka-uka",
        }
        assert c.post(f"/hisob/{student.pk}/chegirma/", form).status_code == 302
        assignment = DiscountAssignment.objects.get()
        assert assignment.value == 1000
        assert (
            c.post(
                f"/chegirmalar/{assignment.pk}/tugatish/", {"valid_to": "01.11.2026"}
            ).status_code
            == 200
        )  # before start
        assert (
            c.post(
                f"/chegirmalar/{assignment.pk}/tugatish/", {"valid_to": "31.12.2026"}
            ).status_code
            == 302
        )
        assignment.refresh_from_db()
        assert assignment.valid_to == D(2026, 12, 31) and assignment.ended_by == admin_a
        d = login(director)
        assert (
            d.post(f"/hisob/{student.pk}/chegirma/", {**form, "value_text": "15"}).status_code
            == 302
        )
        assert DiscountAssignment.objects.filter(value=1500).exists()
        assert AuditLog.objects.filter(action="billing.discount.end").exists()

    def test_plan_edit_screen(self, login, admin_a, student, installment, branch_a, clock):
        g = make_group(admin_a, branch_a, course=installment, start=D(2026, 9, 1), days=MWF)
        e = st.enroll(actor=admin_a, student=student, group=g, start_date=TODAY)
        plan = InstallmentPlan.objects.get(enrollment=e)
        p1, p2, p3 = Charge.objects.filter(plan=plan).order_by("part_no")
        c = login(admin_a)
        url = f"/bolib-tolash-reja/{plan.pk}/"
        assert "1 000 000" in page_text(c.get(url))
        bad = c.post(url, {f"amount_{p2.pk}": "abc", "reason": "x"})
        assert "Summalar va sanalarni tekshiring" in page_text(bad)
        no_reason = c.post(url, {f"amount_{p2.pk}": "900 000"})
        assert no_reason.status_code == 200 and net(p2) == 1_000_000
        ok = c.post(
            url, {f"amount_{p2.pk}": "900 000", f"due_{p3.pk}": "01.03.2027", "reason": "Kelishuv"}
        )
        assert ok.status_code == 302 and net(p2) == 900_000

    def test_lists(self, login, admin_a, student, enrolled, cash):
        pay(admin_a, student, 1000, cash)
        c = login(admin_a)
        assert "Naqd" in page_text(
            c.get("/tolovlar/?dan=01.11.2026&gacha=30.11.2026&usul=" + str(cash.pk))
        )
        assert student.full_name in page_text(c.get("/qarzdorlar/?kun=1&guruh=&kurs=&oqituvchi="))
        assert c.get("/kassa/?sana=bad").status_code == 200
        assert c.get("/tolovlar/yangi/?oquvchi=" + str(student.pk)).status_code == 200
        resp = c.post(
            "/tolovlar/yangi/",
            {"student": student.pk, "amount": "1000", "method": cash.pk, "paid_on": "01.01.2020"},
        )
        assert resp.status_code == 200 and "kun oldin" in page_text(resp)


class TestServiceRules:
    def test_discount_validation(self, admin_a, director, enrolled, installment):
        inactive = percent(name="Eski", is_active=False)
        with pytest.raises(ValidationError):
            services.discounts.assign(
                actor=admin_a, enrollment=enrolled, discount_type=inactive, valid_from=TODAY
            )
        only_inst = fixed(name="Faqat DTM", applies_to="installment")
        with pytest.raises(ValidationError):
            services.discounts.assign(
                actor=admin_a, enrollment=enrolled, discount_type=only_inst, valid_from=TODAY
            )
        locked = percent(name="Qat'iy")
        with pytest.raises(ValidationError):
            services.discounts.assign(
                actor=director,
                enrollment=enrolled,
                discount_type=locked,
                valid_from=TODAY,
                value=2000,
            )
        custom = percent(name="Moslashuvchan", allow_custom_value=True)
        with pytest.raises(PermissionDenied):
            services.discounts.assign(
                actor=admin_a,
                enrollment=enrolled,
                discount_type=custom,
                valid_from=TODAY,
                value=2000,
            )
        with pytest.raises(ValidationError):
            services.discounts.assign(
                actor=director,
                enrollment=enrolled,
                discount_type=custom,
                valid_from=TODAY,
                value=20_000,
            )
        with pytest.raises(ValidationError):
            services.discounts.assign(
                actor=director,
                enrollment=enrolled,
                discount_type=custom,
                valid_from=TODAY,
                valid_to=D(2026, 1, 1),
            )

    def test_ledger_guards(self, admin_a, student, enrolled, branch_a):
        charge = Charge.objects.get(enrollment=enrolled)
        with pytest.raises(ValidationError):
            services.ledger.adjust(
                actor=admin_a, charge=charge, delta=-10_000_000, kind="correction", reason="x"
            )
        with pytest.raises(ValidationError):
            services.ledger.adjust(
                actor=admin_a, charge=charge, delta=-5, kind="correction", suggested=-10
            )
        assert (
            services.ledger.adjust(actor=admin_a, charge=charge, delta=0, kind="correction") is None
        )
        with pytest.raises(ValidationError):
            services.ledger.create_charge(
                actor=admin_a,
                student_id=student.pk,
                branch_id=branch_a.pk,
                kind="manual",
                due_date=TODAY,
                base_amount=1,
                amount=-1,
                suggested_amount=None,
            )
        with pytest.raises(ValidationError):
            services.ledger.create_charge(
                actor=admin_a,
                student_id=student.pk,
                branch_id=branch_a.pk,
                kind="manual",
                due_date=TODAY,
                base_amount=5,
                amount=4,
                suggested_amount=5,
            )

    def test_corrections_guards(self, director, student, enrolled):
        charge = Charge.objects.get(enrollment=enrolled)
        with pytest.raises(ValidationError):
            services.corrections.correct_charge(actor=director, charge=charge, new_net=1, reason="")
        with pytest.raises(ValidationError):
            services.corrections.correct_charge(
                actor=director, charge=charge, new_net=-1, reason="x"
            )
        with pytest.raises(ValidationError):
            services.corrections.manual_charge(
                actor=director, student=student, amount=0, due_date=TODAY, description="x"
            )
        with pytest.raises(ValidationError):
            services.corrections.manual_charge(
                actor=director, student=student, amount=1, due_date=TODAY, description=" "
            )

    def test_payment_guards(self, admin_a, director, student, enrolled, cash, branch_a):
        with pytest.raises(ValidationError):
            pay(admin_a, student, 0, cash)
        p = pay(admin_a, student, 1000, cash)
        r = services.payments.reverse_payment(actor=director, payment=p, reason="x")
        with pytest.raises(ValidationError):  # a reversal itself can't be reversed
            services.payments.reverse_payment(actor=director, payment=r, reason="x")
        with pytest.raises(ValidationError):
            services.payments.refund(
                actor=director, student=student, amount=1, method=cash, reason=" "
            )
        with pytest.raises(ValidationError):
            services.payments.refund(
                actor=director, student=student, amount=0, method=cash, reason="x"
            )
        with pytest.raises(ValidationError):
            services.cash.close_day(actor=director, branch=branch_a, day=D(2026, 11, 17))

    def test_installment_needs_template_and_price(
        self, director, admin_a, branch_a, student, clock
    ):
        from tests.factories import CourseFactory

        course = CourseFactory(pricing_model="installment")
        g = make_group(admin_a, branch_a, course=course, start=D(2026, 9, 1), days=MWF)
        with pytest.raises(ValidationError):  # no template
            st.enroll(actor=admin_a, student=student, group=g, start_date=TODAY)
        from apps.billing.models import InstallmentTemplate

        InstallmentTemplate.objects.create(name="2", parts_count=2, course=course)
        with pytest.raises(ValidationError):  # no full price
            st.enroll(actor=admin_a, student=student, group=g, start_date=TODAY)

    def test_move_between_monthly_and_installment(
        self, director, admin_a, branch_a, student, group, installment
    ):
        ig = make_group(admin_a, branch_a, course=installment, start=D(2026, 9, 1), days=MWF)
        e = st.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 11, 2))
        new = st.move(
            actor=admin_a, enrollment=e, target_group=ig, effective_date=TODAY, reason="DTM"
        )
        assert InstallmentPlan.objects.filter(enrollment=new).exists()
        assert net(Charge.objects.get(enrollment=e)) == 208_000  # 6/13 of the month
        back = st.move(
            actor=admin_a,
            enrollment=new,
            target_group=group,
            effective_date=D(2026, 11, 20),
            reason="qaytdi",
        )
        parts = Charge.objects.filter(enrollment=new).order_by("part_no")
        assert [net(c) for c in parts] == [1_000_000, 0, 0]  # future parts cancelled
        assert Charge.objects.filter(enrollment=back).exists()


@pytest.mark.usefixtures("import_granted")
class TestImportErrors:
    def _upload(self, actor, branch, kind, rows):
        from apps.students.services import importing

        from .test_debtors_and_imports import xlsx

        return importing.validate_upload(
            actor=actor, kind_key=kind, branch=branch, uploaded_file=xlsx(kind, rows)
        )

    def test_opening_balance_errors(self, admin_a, branch_a):
        from apps.students.services import importing

        make_student(admin_a, branch_a, phone="", parent_phone="+998905550000")
        make_student(admin_a, branch_a, phone="", parent_phone="+998905550000")
        names = [str(h) for h, _e in importing.get_kind("opening_balances").columns]
        rows = [
            {names[0]: "", names[1]: 1},
            {names[0]: "12", names[1]: 1},
            {names[0]: "905550000", names[1]: 1},
            {names[0]: "901111111", names[1]: "0", names[2]: "bad"},
        ]
        batch = self._upload(admin_a, branch_a, "opening_balances", rows)
        assert sorted({e["row"] for e in batch.report["errors"]}) == [2, 3, 4, 5]

    def test_discount_import_errors(self, admin_a, branch_a):
        from apps.students.services import importing

        names = [str(h) for h, _e in importing.get_kind("discounts").columns]
        rows = [
            {
                names[0]: "901111111",
                names[1]: "X",
                names[2]: "Yo'q",
                names[3]: "abc",
                names[4]: "bad",
            }
        ]
        batch = self._upload(admin_a, branch_a, "discounts", rows)
        assert len(batch.report["errors"]) >= 3
