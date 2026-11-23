"""Pure check-in rules."""

import datetime as dt

from apps.staff.domain import rules
from apps.staff.forms import parse_coordinates

CHILONZOR = (41.2756, 69.2034)


def test_distance():
    assert rules.distance_m(*CHILONZOR, *CHILONZOR) == 0
    # 0.001 degree of latitude is about 111 m.
    assert 105 <= rules.distance_m(41.2756, 69.2034, 41.2766, 69.2034) <= 115
    # Chilonzor to Yunusobod is several kilometres.
    assert rules.distance_m(*CHILONZOR, 41.3650, 69.2870) > 10_000


def test_nearest_branch():
    a = rules.Place(1, *CHILONZOR, 200)
    b = rules.Place(2, 41.3650, 69.2870, 200)
    match = rules.nearest([a, b], 41.2760, 69.2036)
    assert match.place.branch_id == 1 and match.inside
    far = rules.nearest([a, b], 41.30, 69.24)
    assert not far.inside


def test_late_minutes_and_grace():
    nine = dt.time(9, 0)
    assert rules.late_minutes(nine, dt.time(8, 55), 10) == 0
    assert rules.late_minutes(nine, dt.time(9, 10), 10) == 0  # within grace
    assert rules.late_minutes(nine, dt.time(9, 11), 10) == 11
    assert rules.late_minutes(None, dt.time(12, 0), 10) == 0  # no schedule


def test_status():
    assert rules.status(scheduled=True, works_today=True, checked_in=False, late=0) == "not_yet"
    assert rules.status(scheduled=True, works_today=False, checked_in=False, late=0) == "day_off"
    assert rules.status(scheduled=False, works_today=False, checked_in=False, late=0) == (
        "no_schedule"
    )
    assert rules.status(scheduled=True, works_today=True, checked_in=True, late=5) == "late"
    assert rules.works_on([1, 2, 3], dt.date(2026, 11, 16))  # Monday
    assert not rules.works_on([1, 2, 3], dt.date(2026, 11, 22))  # Sunday


def test_parse_coordinates():
    assert parse_coordinates("41.311081, 69.240562") == (41.311081, 69.240562)
    assert parse_coordinates("41,311081; 69,240562") == (41.311081, 69.240562)
    for bad in ("", "41.3", "abc, def", "95, 69"):
        try:
            parse_coordinates(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
