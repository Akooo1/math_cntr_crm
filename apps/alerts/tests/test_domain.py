import datetime as dt

import pytest

from apps.alerts.domain import absence_streak, debt_round, response_deadline

T = dt.datetime


@pytest.mark.parametrize(
    ("created", "hours", "due"),
    [
        (T(2026, 11, 16, 10, 0), 2, T(2026, 11, 16, 12, 0)),  # inside working hours
        (T(2026, 11, 16, 18, 30), 2, T(2026, 11, 17, 10, 30)),  # 30 min today, 90 tomorrow
        (T(2026, 11, 16, 21, 0), 2, T(2026, 11, 17, 11, 0)),  # evening lead
        (T(2026, 11, 16, 6, 0), 2, T(2026, 11, 16, 11, 0)),  # early morning lead
        (T(2026, 11, 16, 19, 0), 1, T(2026, 11, 17, 10, 0)),  # exactly at closing
        (T(2026, 11, 16, 10, 0), 24, T(2026, 11, 18, 14, 0)),  # 10 h per day
    ],
)
def test_response_deadline(created, hours, due):
    assert response_deadline(created, hours, 9, 19) == due


def test_round_the_clock_and_bad_hours():
    assert response_deadline(T(2026, 11, 16, 23, 0), 2, 0, 24) == T(2026, 11, 17, 1, 0)
    with pytest.raises(ValueError):
        response_deadline(T(2026, 11, 16, 10, 0), 2, 19, 9)


def test_absence_streak():
    assert absence_streak([]) == (0, None)
    assert absence_streak([(5, "present"), (4, "absent")]) == (0, None)
    assert absence_streak([(5, "absent"), (4, "absent"), (3, "present")]) == (2, 4)
    assert absence_streak([(5, "absent")]) == (1, 5)


def test_debt_round():
    assert debt_round(3, 7, 7) is None
    assert debt_round(7, 7, 7) == 0
    assert debt_round(13, 7, 7) == 0
    assert debt_round(14, 7, 7) == 1
    assert debt_round(40, 7, 0) == 0  # no repeats
    assert debt_round(40, 0, 7) is None  # switched off
