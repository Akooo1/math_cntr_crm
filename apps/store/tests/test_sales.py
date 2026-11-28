import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, InternalError, transaction

from apps.billing import services as billing
from apps.billing.models import PaymentMethod
from apps.core.models import AuditLog
from apps.store import selectors, services
from apps.store.models import Sale, SaleLine, SaleReversal

from .factories import TODAY, receive


def sell(actor, branch, method, *lines):
    return services.sell_items(actor=actor, branch=branch, lines=list(lines), method=method)


class TestSellItems:
    def test_basket_with_several_items(self, shop, admin_a, branch_a, cash):
        sale = sell(
            admin_a, branch_a, cash, (shop["small"], 2), (shop["big"], 1), (shop["small"], 1)
        )
        assert sale.total == 3 * 3_000 + 5_000
        assert sale.settlement == "paid" and sale.student is None and sale.sold_on == TODAY
        assert {(line.product_id, line.quantity) for line in sale.lines.all()} == {
            (shop["small"].pk, 3),
            (shop["big"].pk, 1),
        }
        on_hand = selectors.on_hand_map(branch_a.pk)
        assert (on_hand[shop["small"].pk], on_hand[shop["big"].pk]) == (17, 4)
        assert AuditLog.objects.filter(action="store.sale.create", entity_id=str(sale.pk)).exists()

    def test_cannot_sell_more_than_on_hand(self, shop, admin_a, branch_a, cash):
        with pytest.raises(ValidationError, match="1 L suv"):
            sell(admin_a, branch_a, cash, (shop["big"], 6))
        assert not Sale.objects.exists()  # nothing half-written

    def test_cannot_sell_at_zero_in_another_branch(self, shop, director, branch_b, cash):
        with pytest.raises(ValidationError):
            sell(director, branch_b, cash, (shop["small"], 1))

    def test_books_and_inactive_items_are_not_sold_here(
        self, shop, director, admin_a, branch_a, cash
    ):
        with pytest.raises(ValidationError):
            sell(admin_a, branch_a, cash, (shop["book"], 1))
        services.update_product(actor=director, product=shop["big"], is_active=False)
        with pytest.raises(ValidationError):
            sell(admin_a, branch_a, cash, (shop["big"], 1))

    def test_empty_basket_and_bad_quantity(self, shop, admin_a, branch_a, cash):
        with pytest.raises(ValidationError):
            sell(admin_a, branch_a, cash)
        with pytest.raises(ValidationError):
            sell(admin_a, branch_a, cash, (shop["small"], 0))

    def test_method_must_be_a_cash_report_method(self, shop, admin_a, branch_a):
        online = PaymentMethod.objects.create(name="Onlayn", included_in_cash_close=False)
        with pytest.raises(ValidationError):
            sell(admin_a, branch_a, online, (shop["small"], 1))

    def test_roles(self, shop, manager_a, teacher_a, admin_a, branch_a, branch_b, cash):
        from django.http import Http404

        for user in (manager_a, teacher_a):
            with pytest.raises(PermissionDenied):
                sell(user, branch_a, cash, (shop["small"], 1))
        with pytest.raises(Http404):
            sell(admin_a, branch_b, cash, (shop["small"], 1))

    def test_line_amount_is_checked_by_the_database(self, shop, admin_a, branch_a, cash):
        sale = sell(admin_a, branch_a, cash, (shop["small"], 1))
        line = sale.lines.get()
        with pytest.raises((IntegrityError, InternalError)), transaction.atomic():
            SaleLine.objects.create(
                sale=sale,
                product=shop["small"],
                quantity=2,
                price=line.price,
                unit_price=3_000,
                amount=5_000,
            )

    def test_sales_are_append_only(self, shop, admin_a, branch_a, cash):
        sale = sell(admin_a, branch_a, cash, (shop["small"], 1))
        with pytest.raises((IntegrityError, InternalError)), transaction.atomic():
            Sale.objects.filter(pk=sale.pk).update(total=1)
        with pytest.raises((IntegrityError, InternalError)), transaction.atomic():
            SaleLine.objects.filter(sale=sale).delete()


class TestKassa:
    def test_cash_report_counts_sales_per_method_and_source(
        self, shop, admin_a, director, branch_a, cash, terminal, student
    ):
        billing.payments.record_payment(
            actor=admin_a, student=student, amount=100_000, method=cash, paid_on=TODAY
        )
        sell(admin_a, branch_a, cash, (shop["small"], 2))  # 6 000 cash
        card = sell(admin_a, branch_a, terminal, (shop["big"], 2))  # 10 000 card
        services.reverse_sale(actor=director, sale=card, reason="xato")  # card out 10 000
        report = billing.cash.day_report(branch_a.pk, TODAY)
        methods = {m["method"].name: m for m in report["methods"]}
        assert (methods["Naqd"]["in"], methods["Naqd"]["out"]) == (106_000, 0)
        assert (methods["Terminal (karta)"]["in"], methods["Terminal (karta)"]["out"]) == (
            10_000,
            10_000,
        )
        assert report["total_net"] == 106_000
        sources = {s["code"]: s for s in report["sources"]}
        assert sources["payments"]["net"] == 100_000
        assert (sources["store"]["in"], sources["store"]["out"]) == (16_000, 10_000)
        assert len(report["extra_lines"]) == 3

        close = billing.cash.close_day(actor=director, branch=branch_a, day=TODAY)
        store = next(s for s in close.totals["sources"] if s["code"] == "store")
        assert store["net"] == 6_000
        assert close.totals["total_net"] == 106_000

    def test_reopened_day_takes_sales_and_reversals_again(
        self, shop, admin_a, director, branch_a, cash
    ):
        """A Direktor reopened the Kassa day (SPEC §24): the database rules must agree."""
        sale = sell(admin_a, branch_a, cash, (shop["small"], 1))
        billing.cash.close_day(actor=director, branch=branch_a, day=TODAY)
        billing.cash.reopen_day(actor=director, branch=branch_a, day=TODAY, reason="xato")
        sell(admin_a, branch_a, cash, (shop["small"], 1))
        services.reverse_sale(actor=director, sale=sale, reason="xato")

    def test_closed_day_blocks_sales_in_service_and_database(
        self, shop, admin_a, director, branch_a, cash
    ):
        sale = sell(admin_a, branch_a, cash, (shop["small"], 1))
        billing.cash.close_day(actor=director, branch=branch_a, day=TODAY)
        with pytest.raises(ValidationError, match="yopilgan|closed"):
            sell(admin_a, branch_a, cash, (shop["small"], 1))
        with pytest.raises(ValidationError):  # reversal of a paid sale is dated today: locked
            services.reverse_sale(actor=director, sale=sale, reason="x")
        with pytest.raises((InternalError, IntegrityError)), transaction.atomic():  # trigger
            Sale.objects.create(
                branch=branch_a,
                sold_on=TODAY,
                settlement="paid",
                method=cash,
                total=1,
                sold_by=admin_a,
            )
        with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
            SaleReversal.objects.create(
                sale=sale, reversed_on=TODAY, reason="x", created_by=director
            )

    def test_unclosed_day_with_only_sales_is_flagged(self, shop, admin_a, branch_a, cash, clock):
        import datetime as dt

        sell(admin_a, branch_a, cash, (shop["small"], 1))
        clock.shift(dt.timedelta(days=1))
        from apps.billing import selectors as billing_selectors

        days = billing_selectors.unclosed_days(admin_a, None)
        assert [(d["branch_id"], d["date"]) for d in days] == [(branch_a.pk, TODAY)]

    def test_cash_page_and_excel_show_sales(self, shop, admin_a, branch_a, cash, login):
        sell(admin_a, branch_a, cash, (shop["small"], 2))
        c = login(admin_a)
        page = c.get(f"/kassa/?filial={branch_a.pk}").content.decode()
        assert "0,5 L suv × 2" in page
        assert "Savdo" in page
        resp = c.get(f"/kassa/?filial={branch_a.pk}&excel=1")
        assert resp.status_code == 200


class TestReversal:
    def test_reversal_returns_stock_and_is_director_only(
        self, shop, admin_a, director, branch_a, cash
    ):
        sale = sell(admin_a, branch_a, cash, (shop["small"], 4))
        with pytest.raises(PermissionDenied):
            services.reverse_sale(actor=admin_a, sale=sale, reason="x")
        with pytest.raises(ValidationError):
            services.reverse_sale(actor=director, sale=sale, reason=" ")
        rev = services.reverse_sale(actor=director, sale=sale, reason="noto'g'ri bosildi")
        assert rev.reversed_on == TODAY
        assert selectors.on_hand_map(branch_a.pk)[shop["small"].pk] == 20
        with pytest.raises(ValidationError):
            services.reverse_sale(actor=director, sale=sale, reason="yana")
        log = AuditLog.objects.get(action="store.sale.reverse")
        assert log.reason == "noto'g'ri bosildi"

    def test_reversal_on_a_later_day_is_out_on_that_day(
        self, shop, admin_a, director, branch_a, cash, clock
    ):
        import datetime as dt

        sale = sell(admin_a, branch_a, cash, (shop["small"], 1))
        billing.cash.close_day(actor=director, branch=branch_a, day=TODAY)
        clock.shift(dt.timedelta(days=1))
        services.reverse_sale(actor=director, sale=sale, reason="x")
        tomorrow = TODAY + dt.timedelta(days=1)
        report = billing.cash.day_report(branch_a.pk, tomorrow)
        assert report["total_out"] == 3_000 and report["total_in"] == 0


def _run_together(*jobs):
    """Start the jobs at the same moment on their own connections; collect outcomes."""
    import threading

    from django.db import connection

    barrier = threading.Barrier(len(jobs))
    results = [None] * len(jobs)

    def run(i, job):
        try:
            barrier.wait()
            job()
            results[i] = "ok"
        except ValidationError:
            results[i] = "refused"
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_two_cashiers_cannot_both_sell_the_last_unit(director, admin_a, branch_a, cash, clock):
    """The product row lock serialises sales: one wins, the other is told there is none."""
    from .factories import make_product

    item = make_product(director, "Daftar", 2_000)
    receive(director, branch_a, item, 1)

    def job():
        sell(admin_a, branch_a, cash, (item, 1))

    assert sorted(_run_together(job, job)) == ["ok", "refused"]
    assert selectors.on_hand_map(branch_a.pk)[item.pk] == 0


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_a_sale_racing_the_close_is_in_the_snapshot_or_refused(
    director, admin_a, branch_a, cash, clock
):
    """lock_day serialises the close and cash writes: a sale is either counted in the close
    or refused, never saved on a closed day outside its totals."""
    from apps.billing.models import CashDayClose

    from .factories import make_product

    item = make_product(director, "Daftar", 2_000)
    receive(director, branch_a, item, 10)
    outcome = _run_together(
        lambda: sell(admin_a, branch_a, cash, (item, 1)),
        lambda: billing.cash.close_day(actor=director, branch=branch_a, day=TODAY),
    )
    assert outcome[1] == "ok"
    close = CashDayClose.objects.get(branch=branch_a, date=TODAY)
    paid = sum(s.total for s in Sale.objects.filter(branch=branch_a, sold_on=TODAY))
    store = next(s for s in close.totals["sources"] if s["code"] == "store")
    assert store["in"] == paid
