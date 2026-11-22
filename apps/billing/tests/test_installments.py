import datetime as dt

import pytest

from apps.billing.domain.installments import (
    InvalidTemplate,
    TemplateRule,
    build_schedule,
    due_dates,
    split_amounts,
)

D = dt.date


def equal(n, **kw):
    return TemplateRule(parts_count=n, split_mode="equal", first_due="on_start", **kw)


class TestSplit:
    def test_equal_split_remainder_goes_to_part_one(self):
        assert split_amounts(equal(3), 1_000_000, 1000) == [334_000, 333_000, 333_000]

    def test_equal_split_exact(self):
        assert split_amounts(equal(9), 4_950_000, 1000) == [550_000] * 9

    def test_sum_always_equals_total(self):
        for total in (1, 999, 1_000_001, 4_950_000, 2_700_000):
            for n in (2, 3, 7, 9, 12):
                assert sum(split_amounts(equal(n), total, 1000)) == total

    def test_custom_shares(self):
        rule = TemplateRule(3, "custom", "on_start", shares_bp=(4000, 3000, 3000))
        assert split_amounts(rule, 2_700_000, 1000) == [1_080_000, 810_000, 810_000]

    def test_custom_shares_rounding_remainder_on_part_one(self):
        rule = TemplateRule(3, "custom", "on_start", shares_bp=(3334, 3333, 3333))
        parts = split_amounts(rule, 1_000_000, 1000)
        assert parts == [334_000, 333_000, 333_000]


class TestDueDates:
    def test_on_start_monthly_keeps_day_and_clips(self):
        assert due_dates(equal(3), D(2027, 1, 31)) == [
            D(2027, 1, 31),
            D(2027, 2, 28),
            D(2027, 3, 31),
        ]

    def test_on_start_with_due_day_for_later_parts(self):
        assert due_dates(equal(3, due_day_of_month=5), D(2027, 1, 20)) == [
            D(2027, 1, 20),
            D(2027, 2, 5),
            D(2027, 3, 5),
        ]

    def test_fixed_day_same_month_when_not_passed(self):
        rule = TemplateRule(3, "equal", "fixed_day", due_day_of_month=10)
        assert due_dates(rule, D(2027, 1, 8)) == [D(2027, 1, 10), D(2027, 2, 10), D(2027, 3, 10)]

    def test_fixed_day_next_month_when_passed(self):
        rule = TemplateRule(2, "equal", "fixed_day", due_day_of_month=10)
        assert due_dates(rule, D(2027, 1, 11)) == [D(2027, 2, 10), D(2027, 3, 10)]

    def test_interval_and_year_rollover(self):
        rule = equal(3, interval_months=2)
        assert due_dates(rule, D(2026, 11, 15)) == [D(2026, 11, 15), D(2027, 1, 15), D(2027, 3, 15)]


class TestValidation:
    @pytest.mark.parametrize(
        "rule",
        [
            TemplateRule(1, "equal", "on_start"),
            TemplateRule(3, "equal", "fixed_day"),
            TemplateRule(3, "custom", "on_start", shares_bp=(5000, 5000)),
            TemplateRule(2, "custom", "on_start", shares_bp=(6000, 5000)),
            TemplateRule(2, "equal", "on_start", due_day_of_month=31),
        ],
    )
    def test_invalid_rules(self, rule):
        with pytest.raises(InvalidTemplate):
            build_schedule(rule, 1_000_000, D(2027, 1, 1), 1000)

    def test_build_schedule(self):
        parts = build_schedule(equal(3), 1_000_000, D(2027, 1, 15), 1000)
        assert [(p.part_no, p.amount, p.due_date) for p in parts] == [
            (1, 334_000, D(2027, 1, 15)),
            (2, 333_000, D(2027, 2, 15)),
            (3, 333_000, D(2027, 3, 15)),
        ]
