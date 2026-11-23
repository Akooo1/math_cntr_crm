"""Debtors list, payment status, opening balances and discount imports, billing pages."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.billing import selectors, services
from apps.billing.models import Charge, Payment
from apps.students import services as st
from apps.students.services import importing
from tests.factories import make_group, make_student, page_text

from .helpers import MWF, D, net, percent

pytestmark = pytest.mark.django_db


TODAY = D(2026, 11, 16)


def pay(actor, student, amount, method, day=TODAY):
    return services.payments.record_payment(
        actor=actor, student=student, amount=amount, method=method, paid_on=day
    )


class TestDebtors:
    def test_only_overdue_open_amounts_count(self, admin_a, branch_a, group, cash):
        late = make_student(admin_a, branch_a)
        st.enroll(
            actor=admin_a, student=late, group=group, start_date=D(2026, 10, 1)
        )  # Oct due 01.10, Nov due 10.11
        fresh = make_student(admin_a, branch_a)
        st.enroll(
            actor=admin_a, student=fresh, group=group, start_date=D(2026, 11, 16)
        )  # due today: not overdue
        rows = selectors.debtors(admin_a)
        assert [r["student"] for r in rows] == [late]
        oct_net = net(Charge.objects.get(student=late, period_month=D(2026, 10, 1)))
        assert rows[0]["overdue"] == oct_net + 450_000
        assert rows[0]["days"] == (D(2026, 11, 16) - D(2026, 10, 1)).days
        pay(admin_a, late, oct_net, cash)
        rows = selectors.debtors(admin_a)
        assert rows[0]["overdue"] == 450_000 and rows[0]["days"] == 6
        assert rows[0]["last_payment"] == D(2026, 11, 16)

    def test_grace_days_and_filters(
        self, admin_a, director, branch_a, branch_b, group, monthly, clock
    ):
        from apps.core.system_settings import set_settings

        s = make_student(admin_a, branch_a)
        st.enroll(actor=admin_a, student=s, group=group, start_date=D(2026, 11, 2))  # due 02.11
        set_settings({"billing.grace_days": 20}, actor=director)
        assert selectors.debtors(admin_a) == []
        set_settings({"billing.grace_days": 0}, actor=director)
        other = make_group(admin_a, branch_a, course=monthly, start=D(2026, 9, 1), days=MWF)
        assert len(selectors.debtors(admin_a, group=group.pk)) == 1
        assert selectors.debtors(admin_a, group=other.pk) == []
        assert len(selectors.debtors(admin_a, teacher=group.teacher_id)) == 1
        assert selectors.debtors(admin_a, min_days=30) == []
        # branch scope: B's admin view sees nothing of A
        from tests.factories import UserFactory

        admin_b = UserFactory(role="branch_admin", branches=[branch_b])
        assert selectors.debtors(admin_b) == []
        assert len(selectors.debtors(director)) == 1

    def test_payment_status_for_managers(self, admin_a, branch_a, group, cash):
        a, b, c, d = (make_student(admin_a, branch_a) for _ in range(4))
        st.enroll(actor=admin_a, student=a, group=group, start_date=D(2026, 11, 2))  # overdue
        st.enroll(actor=admin_a, student=b, group=group, start_date=D(2026, 11, 2))
        pay(admin_a, b, 450_000, cash)
        st.enroll(actor=admin_a, student=c, group=group, start_date=D(2026, 11, 16))  # due today
        statuses = selectors.payment_statuses([a.pk, b.pk, c.pk, d.pk])
        assert statuses == {a.pk: "debt", b.pk: "paid", c.pk: "waiting", d.pk: "none"}


def xlsx(kind_key, rows):
    kind = importing.get_kind(kind_key)
    wb = Workbook()
    ws = wb.active
    headers = [str(h) for h, _e in kind.columns]
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile("f.xlsx", buf.getvalue())


class TestImports:
    def test_opening_balances_debt_and_credit(self, admin_a, branch_a, clock):
        debtor = make_student(admin_a, branch_a, phone="+998901110001", parent_phone="")
        creditor = make_student(admin_a, branch_a, phone="", parent_phone="+998901110002")
        col = {str(h): h for h, _e in importing.get_kind("opening_balances").columns}
        names = list(col)
        rows = [
            {names[0]: "90 111 00 01", names[1]: 900_000, names[2]: "10.09.2026"},
            {names[0]: "+998901110002", names[1]: -200_000},
        ]
        batch = importing.validate_upload(
            actor=admin_a,
            kind_key="opening_balances",
            branch=branch_a,
            uploaded_file=xlsx("opening_balances", rows),
        )
        assert batch.status == "validated", batch.report
        importing.commit(actor=admin_a, batch=batch, branch=branch_a)
        charge = Charge.objects.get(student=debtor, kind="opening_balance")
        assert charge.due_date == D(2026, 9, 10) and charge.import_batch_id == batch.pk
        assert selectors.balance(debtor.pk) == -900_000
        assert selectors.balance(creditor.pk) == 200_000
        credit = Payment.objects.get(student=creditor)
        assert credit.method.provider_code == "opening_balance"
        report = services.cash.day_report(branch_a.pk, D(2026, 11, 16))
        assert report["total_in"] == 0  # not cash taken today
        # importing again is refused per student
        again = importing.validate_upload(
            actor=admin_a,
            kind_key="opening_balances",
            branch=branch_a,
            uploaded_file=xlsx("opening_balances", rows),
        )
        assert again.status == "failed"

    def test_discount_import(self, admin_a, branch_a, group):
        s = make_student(admin_a, branch_a, phone="+998901110003", parent_phone="")
        e = st.enroll(actor=admin_a, student=s, group=group, start_date=D(2026, 11, 16))
        percent(name="Aka-uka")
        names = [str(h) for h, _e in importing.get_kind("discounts").columns]
        rows = [
            {
                names[0]: "901110003",
                names[1]: group.name,
                names[2]: "aka-uka",
                names[4]: "01.12.2026",
            }
        ]
        batch = importing.validate_upload(
            actor=admin_a,
            kind_key="discounts",
            branch=branch_a,
            uploaded_file=xlsx("discounts", rows),
        )
        assert batch.status == "validated", batch.report
        importing.commit(actor=admin_a, batch=batch, branch=branch_a)
        from apps.billing.models import DiscountAssignment

        assert DiscountAssignment.objects.get(enrollment=e).valid_from == D(2026, 12, 1)


class TestPages:
    def test_take_payment_flow_and_receipt(self, login, admin_a, student, group, cash):
        st.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 11, 2))
        c = login(admin_a)
        assert student.full_name in page_text(c.get("/tolovlar/qidirish/?q=Karimov"))
        resp = c.post(
            "/tolovlar/yangi/",
            {
                "student": student.pk,
                "amount": "450 000",
                "method": cash.pk,
                "paid_on": "16.11.2026",
            },
        )
        payment = Payment.objects.get()
        assert resp.status_code == 302 and resp["Location"] == f"/tolovlar/{payment.pk}/"
        receipt = page_text(c.get(f"/tolovlar/{payment.pk}/chek/"))
        assert "CH-000001" in receipt and "450 000 so'm" in receipt
        profile = page_text(c.get(f"/oquvchilar/{student.pk}/"))
        assert "Balans" in profile

    def test_enroll_confirmation_shows_suggestion(self, login, admin_a, student, group):
        c = login(admin_a)
        url = f"/oquvchilar/{student.pk}/guruhga-qoshish/"
        step = page_text(c.post(url, {"group": group.pk, "date": "16.11.2026"}))
        assert "242 000 so'm" in step and 'name="x_nn202611"' in step
        resp = c.post(
            url,
            {
                "group": group.pk,
                "date": "16.11.2026",
                "x_seen": "1",
                "x_nn202611": "242 000",
                "tasdiq": "1",
            },
        )
        assert resp.status_code == 302
        assert Charge.objects.get().amount == 242_000

    def test_manager_sees_status_not_amounts(self, login, admin_a, manager_a, student, group):
        st.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 11, 2))
        text = page_text(login(manager_a).get(f"/oquvchilar/{student.pk}/"))
        assert "Qarzi bor" in text
        assert "so'm" not in text and "Balans" not in text

    def test_teacher_sees_no_money(self, login, admin_a, teacher_a, branch_a, monthly, clock):
        g = make_group(
            admin_a, branch_a, teacher=teacher_a, course=monthly, start=D(2026, 9, 1), days=MWF
        )
        s = make_student(admin_a, branch_a)
        st.enroll(actor=admin_a, student=s, group=g, start_date=D(2026, 11, 2))
        text = page_text(login(teacher_a).get(f"/oquvchilar/{s.pk}/"))
        assert "so'm" not in text and "Qarzi bor" not in text and "To'lov" not in text

    def test_cash_close_page(self, login, admin_a, branch_a, student, group, cash):
        st.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 11, 2))
        pay(admin_a, student, 100_000, cash)
        c = login(admin_a)
        assert "100 000 so'm" in page_text(c.get("/kassa/"))
        c.post("/kassa/yopish/", {"filial": branch_a.pk, "sana": "16.11.2026"})
        assert services.payments.is_closed(branch_a.pk, D(2026, 11, 16))
