"""Payments: FIFO, credit, receipts, backdating, reversal, refund (SPEC 6.4.5-6.4.8)."""

import threading

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, InternalError, connection, transaction

from apps.billing import selectors, services
from apps.billing.models import Allocation, Charge, Payment, PaymentMethod, ReceiptCounter
from apps.students import services as st

from .helpers import D, net

pytestmark = pytest.mark.django_db
NOV = D(2026, 11, 1)


@pytest.fixture
def enrolled(admin_a, student, group):
    return st.enroll(
        actor=admin_a, student=student, group=group, start_date=D(2026, 10, 1)
    )  # Oct + Nov


TODAY = D(2026, 11, 16)


def pay(actor, student, amount, method, day=TODAY, **kw):
    return services.payments.record_payment(
        actor=actor, student=student, amount=amount, method=method, paid_on=day, **kw
    )


def paid(charge):
    return sum(Allocation.objects.filter(charge=charge).values_list("amount", flat=True))


class TestAllocation:
    def test_oldest_charge_first_then_credit(self, admin_a, student, enrolled, cash):
        oct_, nov = Charge.objects.filter(enrollment=enrolled).order_by("due_date")
        pay(admin_a, student, 500_000, cash)
        assert paid(oct_) == net(oct_) and paid(nov) == 500_000 - net(oct_)
        pay(admin_a, student, 1_000_000, cash)
        assert paid(nov) == 450_000
        assert selectors.balance(student.pk) == 1_500_000 - net(oct_) - 450_000  # credit

    def test_credit_pays_the_next_charge_automatically(
        self, admin_a, student, enrolled, cash, clock
    ):
        pay(admin_a, student, 2_000_000, cash)
        clock.move_to("2026-12-01 09:00+05:00")
        services.monthly.generate_monthly_charges()
        dec = Charge.objects.get(enrollment=enrolled, period_month=D(2026, 12, 1))
        assert paid(dec) == 450_000

    def test_balance_is_the_ledger_sum(self, admin_a, student, enrolled, cash, terminal):
        pay(admin_a, student, 100_000, cash)
        pay(admin_a, student, 50_000, terminal)
        charged = sum(net(c) for c in Charge.objects.filter(student=student))
        assert selectors.balance(student.pk) == 150_000 - charged


class TestReceipts:
    def test_numbers_are_sequential_per_branch(
        self, admin_a, director, student, enrolled, cash, branch_b
    ):
        a = pay(admin_a, student, 1000, cash)
        b = pay(admin_a, student, 1000, cash)
        assert (a.receipt_number, b.receipt_number) == ("CH-000001", "CH-000002")
        from tests.factories import make_student

        other = make_student(director, branch_b)
        c = pay(director, other, 1000, cash)
        assert c.receipt_number == "YU-000001"

    @pytest.mark.django_db(transaction=True, serialized_rollback=True)
    def test_concurrent_payments_get_unique_gapless_numbers(self, admin_a, student, cash, clock):
        errors = []

        def worker():
            try:
                for _ in range(5):
                    pay(admin_a, student, 1000, cash)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        seqs = sorted(Payment.objects.values_list("receipt_seq", flat=True))
        assert seqs == list(range(1, 21))
        assert ReceiptCounter.objects.get().last_seq == 20


class TestRules:
    def test_dates(self, admin_a, student, enrolled, cash):
        with pytest.raises(ValidationError):  # future
            pay(admin_a, student, 1000, cash, D(2026, 11, 17))
        with pytest.raises(ValidationError):  # more than 3 days back
            pay(admin_a, student, 1000, cash, D(2026, 11, 12))
        pay(admin_a, student, 1000, cash, D(2026, 11, 13))

    def test_system_method_and_roles(self, admin_a, manager_a, teacher_a, student, enrolled, cash):
        opening = PaymentMethod.objects.get(provider_code="opening_balance")
        with pytest.raises(ValidationError):
            pay(admin_a, student, 1000, opening)
        for user in (manager_a, teacher_a):
            with pytest.raises(PermissionDenied):
                pay(user, student, 1000, cash)

    def test_admin_cannot_pay_for_other_branch_student(self, admin_a, director, branch_b, cash):
        from django.http import Http404

        from tests.factories import make_student

        other = make_student(director, branch_b)
        with pytest.raises(Http404):
            pay(admin_a, other, 1000, cash)


class TestReversalAndRefund:
    def test_reversal_is_director_only_whole_and_once(
        self, admin_a, director, student, enrolled, cash
    ):
        p = pay(admin_a, student, 300_000, cash)
        with pytest.raises(PermissionDenied):
            services.payments.reverse_payment(actor=admin_a, payment=p, reason="xato")
        with pytest.raises(ValidationError):
            services.payments.reverse_payment(actor=director, payment=p, reason=" ")
        r = services.payments.reverse_payment(
            actor=director, payment=p, reason="Summa xato kiritildi"
        )
        assert (
            r.kind == "reversal"
            and r.amount == 300_000
            and r.reverses == p
            and r.paid_on == D(2026, 11, 16)
        )
        assert not Allocation.objects.exists()  # the charges are open again
        with pytest.raises(ValidationError):
            services.payments.reverse_payment(actor=director, payment=p, reason="yana")

    def test_refund_only_up_to_credit(self, admin_a, director, student, enrolled, cash):
        charged = sum(net(c) for c in Charge.objects.filter(student=student))
        pay(admin_a, student, charged + 200_000, cash)
        with pytest.raises(ValidationError):
            services.payments.refund(
                actor=director, student=student, amount=200_001, method=cash, reason="ketdi"
            )
        with pytest.raises(PermissionDenied):
            services.payments.refund(
                actor=admin_a, student=student, amount=100, method=cash, reason="ketdi"
            )
        services.payments.refund(
            actor=director, student=student, amount=200_000, method=cash, reason="ketdi"
        )
        assert selectors.balance(student.pk) == 0
        assert all(
            paid(c) == net(c) for c in Charge.objects.filter(student=student)
        )  # refund didn't unpay


class TestCashClose:
    def test_close_locks_the_day_in_service_and_database(
        self, admin_a, director, student, enrolled, cash, branch_a
    ):
        pay(admin_a, student, 100_000, cash)
        close = services.cash.close_day(actor=admin_a, branch=branch_a, day=D(2026, 11, 16))
        assert close.totals["total_in"] == 100_000
        with pytest.raises(ValidationError):  # service
            pay(admin_a, student, 1000, cash)
        p = Payment.objects.first()
        with pytest.raises(ValidationError):  # reversal is dated today -> locked too
            services.payments.reverse_payment(actor=director, payment=p, reason="x")
        with pytest.raises((InternalError, IntegrityError)), transaction.atomic():  # trigger
            Payment.objects.create(
                student=student,
                branch=branch_a,
                amount=1,
                method=cash,
                paid_on=D(2026, 11, 16),
                received_by=admin_a,
                receipt_seq=999,
                receipt_number="CH-000999",
            )
        with pytest.raises(ValidationError):
            services.cash.close_day(actor=admin_a, branch=branch_a, day=D(2026, 11, 16))
        pay(admin_a, student, 1000, cash, D(2026, 11, 15))  # other days stay open

    def test_closed_day_does_not_block_methods_outside_the_cash_report(
        self, admin_a, student, enrolled, branch_a
    ):
        services.cash.close_day(actor=admin_a, branch=branch_a, day=D(2026, 11, 16))
        online = PaymentMethod.objects.create(name="Onlayn", included_in_cash_close=False)
        pay(admin_a, student, 1000, online)  # e.g. a future online provider's settlement

    def test_cash_report_by_method_with_refund_and_reversal(
        self, admin_a, director, student, enrolled, cash, terminal, branch_a
    ):
        pay(admin_a, student, 1_000_000, cash)
        p = pay(admin_a, student, 300_000, terminal)
        services.payments.reverse_payment(actor=director, payment=p, reason="xato")
        services.payments.refund(
            actor=director, student=student, amount=50_000, method=cash, reason="ortiqcha"
        )
        report = services.cash.day_report(branch_a.pk, D(2026, 11, 16))
        by = {m["method"].name: m for m in report["methods"]}
        assert (by["Naqd"]["in"], by["Naqd"]["out"]) == (1_000_000, 50_000)
        assert (by["Terminal (karta)"]["in"], by["Terminal (karta)"]["out"]) == (300_000, 300_000)
        assert report["total_net"] == 950_000

    def test_admin_cannot_close_other_branch(self, admin_a, branch_b):
        from django.http import Http404

        with pytest.raises(Http404):
            services.cash.close_day(actor=admin_a, branch=branch_b, day=D(2026, 11, 16))


class TestImmutability:
    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE billing_charge SET amount = 1",
            "DELETE FROM billing_charge",
            "UPDATE billing_payment SET amount = 1",
            "DELETE FROM billing_payment",
            "UPDATE billing_charge_adjustment SET amount = 0",
            "UPDATE billing_charge_discount SET amount = 0",
            "DELETE FROM billing_cash_day_close",
        ],
    )
    def test_ledger_rows_cannot_change(self, admin_a, student, enrolled, cash, branch_a, sql):
        from .helpers import percent

        services.discounts.assign(
            actor=admin_a, enrollment=enrolled, discount_type=percent(), valid_from=D(2026, 1, 1)
        )
        services.corrections.correct_charge  # noqa: B018
        c = Charge.objects.first()
        services.ledger.adjust(actor=admin_a, charge=c, delta=-1000, kind="correction", reason="x")
        services.ledger.create_charge(
            actor=admin_a,
            student_id=student.pk,
            branch_id=branch_a.pk,
            kind="manual",
            due_date=D(2026, 11, 16),
            base_amount=5000,
            amount=5000,
            suggested_amount=None,
            enrollment=enrolled,
        )
        pay(admin_a, student, 1000, cash)
        services.cash.close_day(actor=admin_a, branch=branch_a, day=D(2026, 11, 15))
        with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(sql)

    def test_pending_payment_may_only_become_confirmed(self, admin_a, student, branch_a, cash):
        p = Payment.objects.create(
            student=student,
            branch=branch_a,
            amount=1000,
            method=cash,
            paid_on=D(2026, 11, 16),
            received_by=admin_a,
            receipt_seq=1,
            receipt_number="CH-000001",
            status="pending",
        )
        Payment.objects.filter(pk=p.pk).update(status="confirmed")
        with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
            Payment.objects.filter(pk=p.pk).update(status="pending")


class TestCorrections:
    def test_director_corrects_and_adds_charges(self, admin_a, director, student, enrolled):
        c = Charge.objects.filter(enrollment=enrolled).first()
        with pytest.raises(PermissionDenied):
            services.corrections.correct_charge(actor=admin_a, charge=c, new_net=0, reason="x")
        services.corrections.correct_charge(actor=director, charge=c, new_net=0, reason="Bepul oy")
        assert net(c) == 0
        m = services.corrections.manual_charge(
            actor=director,
            student=student,
            amount=60_000,
            due_date=D(2026, 11, 20),
            description="Kitob",
        )
        assert net(m) == 60_000
