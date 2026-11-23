import datetime as dt

from apps.students.domain.schedule import Slot, is_active_on, is_frozen_on, lesson_plan

D = dt.date
T = dt.time


def test_lesson_plan_follows_weekdays_inclusive():
    slots = [Slot(1, T(15), T(16)), Slot(3, T(15), T(16))]  # Mon, Wed
    plan = lesson_plan(slots, D(2026, 11, 2), D(2026, 11, 11))  # Mon .. Wed next week
    assert [p.date for p in plan] == [
        D(2026, 11, 2),
        D(2026, 11, 4),
        D(2026, 11, 9),
        D(2026, 11, 11),
    ]


def test_two_lessons_same_day_ordered_by_time():
    slots = [Slot(2, T(17), T(18)), Slot(2, T(9), T(10))]
    plan = lesson_plan(slots, D(2026, 11, 3), D(2026, 11, 3))
    assert [p.start_time for p in plan] == [T(9), T(17)]


def test_window_end_is_exclusive():
    assert is_active_on(D(2026, 9, 1), D(2026, 10, 1), D(2026, 9, 30))
    assert not is_active_on(D(2026, 9, 1), D(2026, 10, 1), D(2026, 10, 1))
    assert not is_active_on(D(2026, 9, 1), None, D(2026, 8, 31))


def test_frozen_on():
    freezes = [(D(2026, 10, 10), D(2026, 10, 20)), (D(2026, 11, 1), None)]
    assert is_frozen_on(freezes, D(2026, 10, 10))
    assert not is_frozen_on(freezes, D(2026, 10, 20))
    assert is_frozen_on(freezes, D(2027, 1, 1))
