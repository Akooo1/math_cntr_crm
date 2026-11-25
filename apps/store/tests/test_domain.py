from fractions import Fraction

import pytest

from apps.store.domain import margin, stock


class TestStock:
    def test_on_hand_sums_signed_movements(self):
        # received 20, sold 3 and 2, one sale of 2 cancelled, counted 1 fewer
        assert stock.on_hand([20, -3, -2, 2, -1]) == 16

    def test_merge_lines_adds_repeated_products(self):
        assert stock.merge_lines([("a", 1), ("b", 2), ("a", 3)]) == {"a": 4, "b": 2}

    def test_merge_lines_refuses_zero(self):
        with pytest.raises(ValueError):
            stock.merge_lines([("a", 0)])

    def test_check_available(self):
        stock.check_available({"a": 2}, {"a": 2})
        with pytest.raises(stock.NotEnoughStock) as exc:
            stock.check_available({"a": 3, "b": 1}, {"a": 2})
        assert (exc.value.product_key, exc.value.on_hand, exc.value.wanted) == ("a", 2, 3)

    def test_correction_delta(self):
        assert stock.correction_delta(10, 7) == -3
        assert stock.correction_delta(0, 4) == 4
        with pytest.raises(ValueError):
            stock.correction_delta(3, -1)

    @pytest.mark.parametrize(
        ("qty", "threshold", "low"),
        [(0, 0, True), (5, 0, False), (3, 3, True), (4, 3, False), (-1, 0, True)],
    )
    def test_is_low(self, qty, threshold, low):
        assert stock.is_low(qty, threshold) is low


class TestMargin:
    def test_weighted_average(self):
        # 10 at 2 000 + 30 at 3 000 -> 110 000 / 40 = 2 750 a unit
        assert margin.unit_cost([(10, 20_000), (30, 90_000)]) == Fraction(2750)

    def test_unknown_when_a_receipt_has_no_cost(self):
        assert margin.unit_cost([(10, 20_000), (5, None)]) is None
        assert margin.unit_cost([]) is None

    def test_cost_and_margin_round_to_whole_som(self):
        from apps.billing.services import round_amount

        unit = margin.unit_cost([(3, 10_000)])  # 3 333.33...
        assert margin.cost_of_sold(2, unit) == Fraction(20_000, 3)
        assert round_amount(margin.cost_of_sold(2, unit)) == 6667
        assert margin.margin(10_000, 6667) == 3333
        assert margin.cost_of_sold(2, None) is None
        assert margin.margin(10_000, None) is None
