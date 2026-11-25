import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, InternalError, transaction
from django.http import Http404

from apps.store import selectors, services
from apps.store.models import Price, StockMovement, StockOnHand

from .factories import TODAY, D, make_product, receive


def on_hand(branch, product):
    return selectors.on_hand_map(branch.pk).get(product.pk, 0)


class TestStockMath:
    def test_received_minus_sold_plus_reversals_and_corrections_per_branch(
        self, shop, director, admin_a, branch_a, branch_b, cash
    ):
        small = shop["small"]
        receive(director, branch_b, small, 7)
        sale = services.sell_items(actor=admin_a, branch=branch_a, lines=[(small, 3)], method=cash)
        services.sell_items(actor=admin_a, branch=branch_a, lines=[(small, 2)], method=cash)
        services.reverse_sale(actor=director, sale=sale, reason="xato")
        services.correct_stock(
            actor=director, branch=branch_a, product=small, counted=14, reason="sanaldi"
        )
        # 20 received - 3 - 2 sold + 3 cancelled = 18, counted 14 -> correction -4
        assert on_hand(branch_a, small) == 14
        assert on_hand(branch_b, small) == 7  # other branch untouched
        assert StockMovement.objects.filter(branch=branch_a, product=small).count() == 5
        view = StockOnHand.objects.get(branch=branch_a, product=small)
        assert view.quantity == 14

    def test_on_hand_as_of_a_date(self, shop, director, branch_a):
        receive(director, branch_a, shop["big"], 4, day=D(2026, 11, 14))
        assert selectors.on_hand_map(branch_a.pk, until=D(2026, 11, 13)).get(shop["big"].pk) is None
        assert selectors.on_hand_map(branch_a.pk, until=D(2026, 11, 14))[shop["big"].pk] == 4
        assert selectors.on_hand_map(branch_a.pk)[shop["big"].pk] == 9

    def test_receive_validates(self, shop, director, branch_a):
        with pytest.raises(ValidationError):
            receive(director, branch_a, shop["small"], 0)
        with pytest.raises(ValidationError):
            receive(director, branch_a, shop["small"], 1, day=D(2026, 11, 17))  # future
        with pytest.raises(ValidationError):
            receive(director, branch_a, shop["small"], 1, cost=-1)

    def test_admin_receives_for_own_branch_only(self, shop, admin_a, branch_a, branch_b):
        receive(admin_a, branch_a, shop["small"], 5)
        assert on_hand(branch_a, shop["small"]) == 25
        with pytest.raises(Http404):
            receive(admin_a, branch_b, shop["small"], 5)

    def test_correction_is_director_only_and_needs_a_reason(
        self, shop, admin_a, director, branch_a
    ):
        with pytest.raises(PermissionDenied):
            services.correct_stock(
                actor=admin_a, branch=branch_a, product=shop["small"], counted=1, reason="x"
            )
        with pytest.raises(ValidationError):
            services.correct_stock(
                actor=director, branch=branch_a, product=shop["small"], counted=1, reason=" "
            )
        with pytest.raises(ValidationError):  # nothing to correct
            services.correct_stock(
                actor=director, branch=branch_a, product=shop["small"], counted=20, reason="x"
            )
        with pytest.raises(ValidationError):
            services.correct_stock(
                actor=director, branch=branch_a, product=shop["small"], counted=-1, reason="x"
            )

    def test_correction_is_audited_with_before_and_after(self, shop, director, branch_a):
        from apps.core.models import AuditLog

        services.correct_stock(
            actor=director, branch=branch_a, product=shop["big"], counted=2, reason="singan"
        )
        log = AuditLog.objects.get(action="store.stock.correct")
        assert log.before == {"on_hand": 5}
        assert log.after["on_hand"] == 2
        assert log.reason == "singan"
        assert log.branch_id == branch_a.pk


class TestAppendOnly:
    def test_movements_and_prices_cannot_change(self, shop):
        mv = StockMovement.objects.first()
        with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
            StockMovement.objects.filter(pk=mv.pk).update(quantity=99)
        with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
            StockMovement.objects.filter(pk=mv.pk).delete()
        with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
            Price.objects.filter(product=shop["small"]).update(amount=1)

    def test_sign_constraints(self, shop, director, branch_a):
        with pytest.raises(IntegrityError), transaction.atomic():
            StockMovement.objects.create(
                branch=branch_a,
                product=shop["small"],
                kind="receipt",
                quantity=-1,
                movement_date=TODAY,
                created_by=director,
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            StockMovement.objects.create(
                branch=branch_a,
                product=shop["small"],
                kind="correction",
                quantity=-1,
                movement_date=TODAY,
                created_by=director,
            )


class TestCatalog:
    def test_price_history_keeps_sold_price(self, shop, director, admin_a, branch_a, cash):
        sale = services.sell_items(
            actor=admin_a, branch=branch_a, lines=[(shop["small"], 1)], method=cash
        )
        services.add_price(
            actor=director, product=shop["small"], amount=4_000, effective_from=TODAY
        )
        later = services.sell_items(
            actor=admin_a, branch=branch_a, lines=[(shop["small"], 1)], method=cash
        )
        assert sale.lines.get().unit_price == 3_000
        assert later.lines.get().unit_price == 4_000
        assert selectors.current_prices()[shop["small"].pk].amount == 4_000

    def test_future_price_not_used_yet(self, shop, director, admin_a, branch_a, cash):
        services.add_price(
            actor=director, product=shop["small"], amount=9_000, effective_from=D(2026, 12, 1)
        )
        sale = services.sell_items(
            actor=admin_a, branch=branch_a, lines=[(shop["small"], 1)], method=cash
        )
        assert sale.total == 3_000

    def test_only_director_manages_catalog(self, shop, admin_a):
        with pytest.raises(PermissionDenied):
            make_product(admin_a, "Ruchka", 2_000)
        with pytest.raises(PermissionDenied):
            services.add_price(actor=admin_a, product=shop["small"], amount=1, effective_from=TODAY)

    def test_duplicate_name_refused(self, shop, director):
        with pytest.raises(ValidationError):
            make_product(director, "0,5 L suv", 1_000)
        with pytest.raises(ValidationError):
            services.update_product(actor=director, product=shop["big"], name="0,5 L suv")

    def test_update_is_audited(self, shop, director):
        from apps.core.models import AuditLog

        services.update_product(actor=director, product=shop["big"], low_stock_threshold=8)
        log = AuditLog.objects.get(action="store.product.update")
        assert log.after == {"low_stock_threshold": 8}
