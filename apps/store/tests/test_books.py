import datetime as dt

import pytest
from django.core.exceptions import ValidationError

from apps.billing import selectors as billing_selectors
from apps.billing import services as billing
from apps.billing.models import Allocation, Charge, ChargeNet
from apps.core.system_settings import set_settings
from apps.store import selectors, services
from apps.store.models import Sale
from apps.students import services as student_services
from tests.factories import make_student

from .factories import TODAY


def give(actor, student, book, qty=1, method=None):
    return services.give_book(
        actor=actor, student=student, product=book, quantity=qty, method=method
    )


class TestPayLater:
    def test_becomes_a_manual_charge_due_in_n_days(self, shop, admin_a, student):
        sale = give(admin_a, student, shop["book"], 2)
        charge = sale.charge
        assert sale.settlement == "on_account" and sale.method is None
        assert charge.kind == Charge.Kind.MANUAL
        assert charge.group_id is None and charge.course_id is None
        assert charge.amount == 120_000 and charge.base_amount == 120_000
        assert charge.due_date == TODAY + dt.timedelta(days=7)
        assert "Algebra 7" in charge.description
        assert billing_selectors.balance(student.pk) == -120_000
        assert selectors.on_hand_map(student.branch_id)[shop["book"].pk] == 8

    def test_due_days_follow_the_setting(self, shop, admin_a, director, student):
        set_settings({"store.book_due_days": 14}, actor=director)
        sale = give(admin_a, student, shop["book"])
        assert sale.charge.due_date == TODAY + dt.timedelta(days=14)

    def test_is_a_debt_after_the_due_date_and_a_later_payment_clears_it(
        self, shop, admin_a, student, cash, clock
    ):
        sale = give(admin_a, student, shop["book"])
        assert billing_selectors.debtors(admin_a) == []
        clock.shift(dt.timedelta(days=8))
        debtors = billing_selectors.debtors(admin_a)
        assert [d["student"].pk for d in debtors] == [student.pk]
        assert debtors[0]["overdue"] == 60_000
        billing.payments.record_payment(
            actor=admin_a,
            student=student,
            amount=60_000,
            method=cash,
            paid_on=TODAY + dt.timedelta(days=8),
        )
        row = ChargeNet.objects.get(pk=sale.charge_id)
        assert row.paid == row.net == 60_000
        assert billing_selectors.debtors(admin_a) == []
        assert selectors.student_books(admin_a, student)[0]["status"] == "paid"

    def test_never_counts_toward_a_teacher_salary(
        self, shop, admin_a, director, student, cash, group
    ):
        set_settings({"salaries.start_month": 202611}, actor=director)
        student_services.enroll(actor=admin_a, student=student, group=group, start_date=TODAY)
        sale = give(admin_a, student, shop["book"])
        billing.payments.record_payment(
            actor=admin_a, student=student, amount=2_000_000, method=cash, paid_on=TODAY
        )
        from apps.salaries.selectors import live_basis

        book_alloc = Allocation.objects.get(charge_id=sale.charge_id)
        assert book_alloc.amount == 60_000
        basis_total = sum(live_basis(TODAY).values())
        group_paid = sum(a.amount for a in Allocation.objects.filter(charge__group__isnull=False))
        assert group_paid > 0
        assert basis_total == group_paid  # the book's 60 000 is not in it

    def test_existing_credit_pays_the_book(self, shop, admin_a, student, cash):
        billing.payments.record_payment(
            actor=admin_a, student=student, amount=100_000, method=cash, paid_on=TODAY
        )
        sale = give(admin_a, student, shop["book"])
        assert ChargeNet.objects.get(pk=sale.charge_id).paid == 60_000
        assert billing_selectors.balance(student.pk) == 40_000

    def test_reversal_cancels_the_charge_and_returns_the_book(
        self, shop, admin_a, director, student
    ):
        sale = give(admin_a, student, shop["book"])
        services.reverse_sale(actor=director, sale=sale, reason="qaytardi")
        assert ChargeNet.objects.get(pk=sale.charge_id).net == 0
        assert billing_selectors.balance(student.pk) == 0
        assert selectors.on_hand_map(student.branch_id)[shop["book"].pk] == 10
        assert selectors.student_books(admin_a, student)[0]["status"] == "cancelled"
        report = billing.cash.day_report(student.branch_id, TODAY)
        assert report["total_out"] == 0  # no cash moved

    def test_on_account_book_is_not_blocked_by_a_closed_day(
        self, director, shop, admin_a, student, branch_a
    ):
        billing.cash.close_day(actor=director, branch=branch_a, day=TODAY)
        assert give(admin_a, student, shop["book"]).settlement == "on_account"


class TestPayNow:
    def test_store_sale_outside_the_ledger(self, shop, admin_a, student, cash):
        sale = give(admin_a, student, shop["book"], method=cash)
        assert sale.settlement == "paid" and sale.student == student and sale.charge is None
        assert not Charge.objects.filter(student=student).exists()
        assert billing_selectors.balance(student.pk) == 0
        report = billing.cash.day_report(student.branch_id, TODAY)
        assert report["total_in"] == 60_000
        assert selectors.student_books(admin_a, student)[0]["status"] == "paid"

    def test_closed_day_blocks_pay_now(self, director, shop, admin_a, student, cash, branch_a):
        billing.cash.close_day(actor=director, branch=branch_a, day=TODAY)
        with pytest.raises(ValidationError):
            give(admin_a, student, shop["book"], method=cash)

    def test_out_of_stock_and_wrong_kind(self, shop, admin_a, student, director, branch_b):
        with pytest.raises(ValidationError):
            give(admin_a, student, shop["book"], 11)
        with pytest.raises(ValidationError):
            give(admin_a, student, shop["small"])
        other = make_student(director, branch_b)
        with pytest.raises(ValidationError):  # branch B has no books
            give(director, other, shop["book"])
        assert not Sale.objects.exists()


class TestGroup:
    @pytest.fixture
    def roster(self, admin_a, branch_a, group):
        students = [make_student(admin_a, branch_a, first_name=f"S{i}") for i in range(3)]
        enrollments = [
            student_services.enroll(actor=admin_a, student=s, group=group, start_date=TODAY)
            for s in students
        ]
        return students, enrollments

    def test_one_book_and_one_charge_per_ticked_student(self, shop, admin_a, group, roster):
        students, _ = roster
        sales = services.give_books_to_group(
            actor=admin_a,
            group=group,
            product=shop["book"],
            student_ids=[s.pk for s in students[:2]],
        )
        assert len(sales) == 2
        assert all(s.charge.amount == 60_000 for s in sales)
        assert {s.student_id for s in sales} == {students[0].pk, students[1].pk}
        assert selectors.on_hand_map(group.branch_id)[shop["book"].pk] == 8

    def test_all_or_nothing_when_stock_is_short(self, shop, admin_a, director, group, roster):
        students, _ = roster
        services.correct_stock(
            actor=director, branch=group.branch, product=shop["book"], counted=2, reason="sanaldi"
        )
        with pytest.raises(ValidationError):
            services.give_books_to_group(
                actor=admin_a,
                group=group,
                product=shop["book"],
                student_ids=[s.pk for s in students],
            )
        assert not Sale.objects.exists()
        assert not Charge.objects.filter(kind="manual").exists()

    def test_only_students_of_the_group(self, shop, admin_a, branch_a, group, roster):
        outsider = make_student(admin_a, branch_a, first_name="Begona")
        with pytest.raises(ValidationError):
            services.give_books_to_group(
                actor=admin_a, group=group, product=shop["book"], student_ids=[outsider.pk]
            )
        with pytest.raises(ValidationError):
            services.give_books_to_group(
                actor=admin_a, group=group, product=shop["book"], student_ids=[]
            )
