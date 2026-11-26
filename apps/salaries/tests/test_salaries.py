"""Teacher salaries end to end (docs/SPEC.md §13). Clock: Monday 16.11.2026 10:00 Tashkent."""

import datetime as dt
import io

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from openpyxl import load_workbook

from apps.billing import services as billing
from apps.billing.tests.helpers import MWF, NOW, D
from apps.core.roles import Role
from apps.core.system_settings import set_settings
from apps.salaries import selectors, services
from apps.salaries.models import Adjustment, Line, Month, Payout
from apps.students import services as st
from apps.students.models import Group
from tests.factories import UserFactory, make_group, make_student, page_text

pytestmark = pytest.mark.django_db

OCT, NOV, DEC, JAN = D(2026, 10, 1), D(2026, 11, 1), D(2026, 12, 1), D(2027, 1, 1)
TODAY = D(2026, 11, 16)


@pytest.fixture
def setup(clock, director, admin_a, branch_a, monthly):
    set_settings({"salaries.start_month": 202611}, actor=director)
    teacher = UserFactory(role=Role.TEACHER, branches=[branch_a], full_name="Ustoz Aliyev")
    group = make_group(
        admin_a, branch_a, teacher=teacher, course=monthly, start=D(2026, 9, 1), days=MWF
    )
    student = make_student(admin_a, branch_a)
    st.enroll(actor=admin_a, student=student, group=group, start_date=OCT)  # Oct + Nov charged
    return {"teacher": teacher, "group": group, "student": student}


def pay(actor, student, amount, method, day=TODAY):
    return billing.payments.record_payment(
        actor=actor, student=student, amount=amount, method=method, paid_on=day
    )


def sheet(director, teacher, month):
    return selectors.sheet(director, teacher.pk, month)


class TestCalculation:
    def test_half_of_money_actually_paid(self, setup, director, admin_a, cash):
        assert sheet(director, setup["teacher"], NOV).totals.total == 0  # charged, not paid
        pay(admin_a, setup["student"], 300_000, cash)
        s = sheet(director, setup["teacher"], NOV)
        # The October fee paid in November counts in November.
        assert [(line["payment_month"], line["base"], line["amount"]) for line in s.lines] == [
            (NOV, 300_000, 150_000)
        ]
        assert s.totals.total == 150_000

    def test_owner_rate(self, setup, director, admin_a, cash):
        services.add_rate(
            actor=director, teacher=setup["teacher"], rate_bp=6500, effective_from=OCT
        )
        pay(admin_a, setup["student"], 300_000, cash)
        assert sheet(director, setup["teacher"], NOV).totals.total == 195_000

    def test_credit_not_counted_until_applied(self, setup, director, admin_a, cash):
        pay(admin_a, setup["student"], 1_000_000, cash)  # Oct + Nov = 900 000, 100 000 credit
        assert sheet(director, setup["teacher"], NOV).totals.paid == 900_000

    def test_payments_before_start_month_ignored(self, setup, director, admin_a, cash):
        set_settings({"salaries.start_month": 202612}, actor=director)
        pay(admin_a, setup["student"], 300_000, cash)
        assert selectors.open_month() == DEC
        assert sheet(director, setup["teacher"], DEC).totals.total == 0

    def test_charges_without_group_earn_nothing(self, setup, director, admin_a, cash):
        # A textbook charged before the fees is paid first (FIFO) and has no teacher.
        billing.corrections.manual_charge(
            actor=director,
            student=setup["student"],
            amount=100_000,
            due_date=D(2026, 9, 1),
            description="kitob",
        )
        pay(admin_a, setup["student"], 300_000, cash)
        s = sheet(director, setup["teacher"], NOV)
        assert (s.totals.paid, s.totals.total) == (200_000, 100_000)


class TestClosing:
    def test_close_freezes_and_later_reversal_corrects_next_month(
        self, setup, director, admin_a, cash, clock
    ):
        payment = pay(admin_a, setup["student"], 300_000, cash)
        services.close_month(actor=director, month=NOV)
        assert Line.objects.filter(month__month=NOV).count() == 1
        assert selectors.open_month() == DEC
        # Closed November doesn't move; the reversal shows up in December.
        billing.payments.reverse_payment(actor=director, payment=payment, reason="xato")
        assert sheet(director, setup["teacher"], NOV).totals.total == 150_000
        dec = sheet(director, setup["teacher"], DEC)
        assert [(line["kind"], line["payment_month"], line["amount"]) for line in dec.lines] == [
            ("correction", NOV, -150_000)
        ]
        # A negative month is carried over, not paid.
        clock.move_to(dt.datetime(2026, 12, 31, 5, 0, tzinfo=dt.UTC))
        services.close_month(actor=director, month=DEC)
        carry = Adjustment.objects.get(month=JAN, teacher=setup["teacher"])
        assert carry.kind == "carry" and carry.amount == -150_000
        with pytest.raises(ValidationError):
            services.pay_out(
                actor=director, teacher=setup["teacher"], month=DEC, paid_on=D(2026, 12, 31)
            )

    def test_months_close_in_order_and_not_early(self, setup, director):
        with pytest.raises(ValidationError):
            services.close_month(actor=director, month=DEC)  # November is still open
        services.close_month(actor=director, month=NOV)
        with pytest.raises(ValidationError):
            services.close_month(actor=director, month=DEC)  # hasn't started
        with pytest.raises(ValidationError):
            services.close_month(actor=director, month=NOV)  # already closed

    def test_teacher_change_keeps_closed_months(self, setup, director, admin_a, branch_a, cash):
        pay(admin_a, setup["student"], 300_000, cash)
        services.close_month(actor=director, month=NOV)
        new = UserFactory(role=Role.TEACHER, branches=[branch_a], full_name="Yangi ustoz")
        Group.objects.filter(pk=setup["group"].pk).update(teacher=new)
        pay(admin_a, setup["student"], 600_000, cash)  # rest of Oct + Nov
        assert sheet(director, setup["teacher"], NOV).totals.total == 150_000
        dec_new = sheet(director, new, DEC)
        assert dec_new.totals.corrections == 300_000  # Nov money, new teacher, next month
        assert sheet(director, setup["teacher"], DEC).totals.total == 0

    def test_rate_change_never_touches_closed_months(self, setup, director, admin_a, cash):
        pay(admin_a, setup["student"], 300_000, cash)
        services.close_month(actor=director, month=NOV)
        with pytest.raises(ValidationError):
            services.add_rate(
                actor=director, teacher=setup["teacher"], rate_bp=6500, effective_from=NOV
            )
        services.add_rate(
            actor=director, teacher=setup["teacher"], rate_bp=6500, effective_from=DEC
        )
        assert sheet(director, setup["teacher"], NOV).totals.total == 150_000


class TestAdjustmentsAndPayouts:
    def test_bonus_deduction_and_lock(self, setup, director, admin_a, cash):
        pay(admin_a, setup["student"], 300_000, cash)
        t = setup["teacher"]
        bonus = services.add_adjustment(
            actor=director, teacher=t, month=NOV, kind="bonus", amount=50_000, reason="olimpiada"
        )
        services.add_adjustment(
            actor=director, teacher=t, month=NOV, kind="deduction", amount=20_000, reason="kech"
        )
        assert sheet(director, t, NOV).totals.total == 150_000 + 50_000 - 20_000
        services.delete_adjustment(actor=director, adjustment=bonus)
        assert sheet(director, t, NOV).totals.total == 130_000
        services.close_month(actor=director, month=NOV)
        with pytest.raises(ValidationError):
            services.add_adjustment(
                actor=director, teacher=t, month=NOV, kind="bonus", amount=1, reason="x"
            )
        adj = Adjustment.objects.get(month=NOV)
        with pytest.raises(ValidationError):
            services.delete_adjustment(actor=director, adjustment=adj)
        with pytest.raises(IntegrityError), transaction.atomic():  # the trigger, too
            Adjustment.objects.filter(pk=adj.pk).delete()

    def test_payout_once_cancel_and_not_in_cash_report(
        self, setup, director, admin_a, branch_a, cash
    ):
        pay(admin_a, setup["student"], 300_000, cash)
        t = setup["teacher"]
        with pytest.raises(ValidationError):  # not closed yet
            services.pay_out(actor=director, teacher=t, month=NOV, paid_on=D(2026, 11, 16))
        services.close_month(actor=director, month=NOV)
        cash_before = billing.cash.day_report(branch_a.pk, D(2026, 11, 16))["total_net"]
        p = services.pay_out(actor=director, teacher=t, month=NOV, paid_on=D(2026, 11, 16))
        assert p.amount == 150_000
        assert billing.cash.day_report(branch_a.pk, D(2026, 11, 16))["total_net"] == cash_before
        with pytest.raises(ValidationError):
            services.pay_out(actor=director, teacher=t, month=NOV, paid_on=D(2026, 11, 16))
        services.cancel_payout(actor=director, payout=p, reason="noto'g'ri sana")
        assert sheet(director, t, NOV).payout is None
        services.pay_out(actor=director, teacher=t, month=NOV, paid_on=D(2026, 11, 15))
        assert sheet(director, t, NOV).payout.paid_on == D(2026, 11, 15)

    def test_append_only_tables(self, setup, director, admin_a, cash):
        pay(admin_a, setup["student"], 300_000, cash)
        services.close_month(actor=director, month=NOV)
        for model in (Line, Month):
            with pytest.raises(IntegrityError), transaction.atomic():
                model.objects.all().delete()
        with pytest.raises(IntegrityError), transaction.atomic():
            Line.objects.update(amount=1)
        assert Line.objects.count() == 1

    def test_db_checks(self, setup, director):
        with pytest.raises(IntegrityError), transaction.atomic():
            Adjustment.objects.create(
                month=NOV, teacher=setup["teacher"], kind="bonus", amount=-5, reason="x"
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            Adjustment.objects.create(
                month=D(2026, 11, 5), teacher=setup["teacher"], kind="bonus", amount=5, reason="x"
            )
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM salaries_payout")
            assert cur.fetchone()[0] == Payout.objects.count() == 0


class TestAccess:
    def test_teacher_sees_only_own(self, setup, director, admin_a, teacher_a, manager_a, cash):
        pay(admin_a, setup["student"], 300_000, cash)
        mine = selectors.sheet(setup["teacher"], setup["teacher"].pk, NOV)
        assert mine.totals.total == 150_000
        with pytest.raises(Http404):
            selectors.sheet(teacher_a, setup["teacher"].pk, NOV)
        for user in (admin_a, manager_a):  # staff see only their own sheet
            with pytest.raises(Http404):
                selectors.sheet(user, setup["teacher"].pk, NOV)
        with pytest.raises(PermissionDenied):
            services.close_month(actor=admin_a, month=OCT)

    def test_pages(self, setup, login, director, admin_a, cash):
        pay(admin_a, setup["student"], 300_000, cash)
        client = login(director)
        text = page_text(client.get("/maosh/?oy=11.2026"))
        assert "Ustoz Aliyev" in text and "150 000" in text.replace(" ", " ")
        resp = client.get("/maosh/?oy=11.2026&excel=1")
        ws = load_workbook(io.BytesIO(resp.content)).active
        assert [c.value for c in ws[1]][:3] == ["Xodim", "To'langan pul", "Ulush"]
        assert ws.cell(row=2, column=3).value == 150_000
        sheet_text = page_text(client.get(f"/maosh/oqituvchi/{setup['teacher'].pk}/?oy=11.2026"))
        assert "Karimov Aziz" in sheet_text
        teacher_client = login(setup["teacher"])
        assert "Karimov Aziz" in page_text(teacher_client.get("/maoshim/?oy=11.2026"))
        assert teacher_client.get("/maosh/").status_code == 403

    def test_close_and_payout_through_views(self, setup, login, director, admin_a, cash):
        pay(admin_a, setup["student"], 300_000, cash)
        client = login(director)
        client.post("/maosh/yopish/", {"oy": "11.2026"})
        assert selectors.open_month() == DEC
        t = setup["teacher"].pk
        client.post(f"/maosh/oqituvchi/{t}/berish/", {"oy": "11.2026", "paid_on": "16.11.2026"})
        assert Payout.objects.filter(teacher_id=t, amount=150_000).exists()
        client.post(
            f"/maosh/oqituvchi/{t}/qoshish/",
            {"oy": "12.2026", "kind": "bonus", "amount": "10 000", "reason": "a'lo"},
        )
        assert Adjustment.objects.get(teacher_id=t).amount == 10_000


def test_now_is_frozen(clock):
    from apps.core import dates

    assert dates.now().astimezone(dt.UTC) == NOW
