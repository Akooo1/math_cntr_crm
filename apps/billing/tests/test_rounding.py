from fractions import Fraction

import pytest

from apps.billing.domain.rounding import floor_to_step, percent_of, round_amount


@pytest.mark.parametrize(
    "value,step,expected",
    [
        (237_461, 1000, 237_000),
        (237_500, 1000, 238_000),  # half goes up
        (237_499, 1000, 237_000),
        (Fraction(450_000 * 7, 12), 1000, 263_000),  # 262 500 -> 263 000
        (Fraction(450_000 * 7, 12), 100, 262_500),
        (Fraction(1, 2), 1, 1),
        (-237_500, 1000, -238_000),  # symmetric for negative adjustments
        (0, 1000, 0),
    ],
)
def test_round_amount_half_up(value, step, expected):
    assert round_amount(value, step) == expected


def test_round_amount_rejects_bad_step():
    with pytest.raises(ValueError):
        round_amount(100, 0)


def test_floor_to_step():
    assert floor_to_step(Fraction(1_000_000, 3), 1000) == 333_000
    assert floor_to_step(999, 1000) == 0


@pytest.mark.parametrize(
    "amount,bp,step,expected",
    [(450_000, 1000, 1000, 45_000), (375_000, 1500, 1000, 56_000), (375_000, 1500, 1, 56_250)],
)
def test_percent_of(amount, bp, step, expected):
    assert percent_of(amount, bp, step) == expected
