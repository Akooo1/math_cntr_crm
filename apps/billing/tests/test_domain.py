"""Pure money math: proration, discounts, FIFO allocation. No database."""

import datetime as dt

import pytest

from apps.billing.domain import allocation, discounts, proration

D = dt.date
NOV = [D(2026, 11, d) for d in (2, 4, 6, 9, 11, 13, 16, 18, 20, 23, 25, 27, 30)]  # 13 lessons


class TestProration:
    def test_join_mid_month(self):
        n = proration.billable_lessons(NOV, (D(2026, 11, 16), None))
        assert n == 7
        assert proration.prorate(450_000, n, 13, 1000) == 242_000  # 242 307.69 -> 242 000

    def test_join_on_or_before_first_lesson_is_full_price(self):
        assert proration.billable_lessons(NOV, (D(2026, 11, 1), None)) == 13
        assert proration.prorate(450_000, 13, 13, 1000) == 450_000

    def test_leave_end_date_is_exclusive(self):
        n = proration.billable_lessons(NOV, (D(2026, 9, 1), D(2026, 11, 11)))
        assert n == 4  # 2, 4, 6, 9 - the 11th is the first day not attending

    def test_freeze_window_exact(self):
        frozen = [(D(2026, 11, 9), D(2026, 11, 23))]
        assert proration.billable_lessons(NOV, (D(2026, 9, 1), None), frozen) == 7

    def test_no_lessons_means_zero(self):
        assert proration.prorate(450_000, 0, 0, 1000) == 0
        assert proration.prorate(450_000, 0, 13, 1000) == 0

    @pytest.mark.parametrize("step,expected", [(1, 242_308), (100, 242_300), (1000, 242_000)])
    def test_rounding_step(self, step, expected):
        assert proration.prorate(450_000, 7, 13, step) == expected


class TestDiscounts:
    R = discounts.Rule

    def test_percents_add_then_fixed(self):
        rules = [
            self.R("promo", "fixed", 50_000),
            self.R("aka", "percent", 1000),
            self.R("ijt", "percent", 500),
        ]
        assert discounts.lines(450_000, rules, 1000) == [
            ("aka", 45_000),
            ("ijt", 23_000),
            ("promo", 50_000),
        ]
        assert discounts.net(450_000, rules, 1000) == 332_000

    def test_never_below_zero(self):
        rules = [self.R("a", "percent", 8000), self.R("b", "fixed", 200_000)]
        assert discounts.lines(450_000, rules, 1000) == [("a", 360_000), ("b", 90_000)]
        assert discounts.net(450_000, rules, 1000) == 0

    def test_hundred_percent(self):
        assert discounts.net(300_000, [self.R("x", "percent", 10_000)], 1000) == 0

    def test_spread_fixed_discount_over_parts(self):
        assert discounts.spread(100_000, [334_000, 333_000, 333_000], 1000) == [
            34_000,
            33_000,
            33_000,
        ]
        assert sum(discounts.spread(99_999, [1, 1, 1], 1000)) == 99_999
        assert discounts.spread(5, [], 1000) == []


C = allocation.OpenCharge
P = allocation.Money


class TestAllocation:
    def test_oldest_charge_first_and_credit(self):
        charges = [C(2, D(2026, 11, 10), (2,), 450_000), C(1, D(2026, 10, 10), (1,), 450_000)]
        pays = [P(10, D(2026, 11, 1), (10,), 600_000), P(11, D(2026, 11, 20), (11,), 400_000)]
        allocs, credit = allocation.allocate(charges, pays)
        assert allocs == [(10, 1, 450_000), (10, 2, 150_000), (11, 2, 300_000)]
        assert credit == 100_000

    def test_new_charge_consumes_existing_credit(self):
        pays = [P(10, D(2026, 10, 1), (10,), 500_000)]
        _a, credit = allocation.allocate([], pays)
        assert credit == 500_000
        allocs, credit = allocation.allocate([C(1, D(2026, 11, 10), (1,), 450_000)], pays)
        assert allocs == [(10, 1, 450_000)] and credit == 50_000

    def test_refund_is_taken_from_newest_money(self):
        charges = [C(1, D(2026, 11, 10), (1,), 300_000)]
        pays = [P(10, D(2026, 11, 1), (10,), 300_000), P(11, D(2026, 11, 2), (11,), 200_000)]
        allocs, credit = allocation.allocate(charges, pays, refunded=200_000)
        assert allocs == [(10, 1, 300_000)] and credit == 0

    def test_future_installment_parts_are_paid_in_order(self):
        parts = [C(i, D(2026, 9 + i, 5), (i,), 1_000_000) for i in (1, 2, 3)]
        allocs, credit = allocation.allocate(parts, [P(9, D(2026, 9, 1), (9,), 2_500_000)])
        assert allocs == [(9, 1, 1_000_000), (9, 2, 1_000_000), (9, 3, 500_000)] and credit == 0

    def test_zero_net_charges_take_nothing(self):
        allocs, credit = allocation.allocate(
            [C(1, D(2026, 11, 1), (1,), 0)], [P(9, D(2026, 11, 1), (9,), 10)]
        )
        assert allocs == [] and credit == 10
