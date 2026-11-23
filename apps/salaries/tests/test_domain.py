"""Pure salary math (no database)."""

import datetime as dt

from apps.billing.domain.rounding import percent_of
from apps.salaries.domain import calc
from apps.salaries.formatting import format_percent, parse_percent

D = dt.date
OCT, NOV, DEC = D(2026, 10, 1), D(2026, 11, 1), D(2026, 12, 1)


def rate_for(rates):
    return lambda teacher, month: rates.get(teacher, 5000)


def test_share_and_correction_lines():
    live = {(1, 10, NOV): 300_000, (2, 10, OCT): 450_000, (3, 10, DEC): 99}
    accounted = {(2, 10, OCT): 450_000, (4, 10, OCT): 200_000}
    lines = calc.draft_lines(NOV, live, accounted, {10: 7}, rate_for({}), percent_of)
    by_student = {line.student_id: line for line in lines}
    # Student 1 paid this month: a share line.
    assert by_student[1].kind == calc.SHARE and by_student[1].amount == 150_000
    # Student 2 was fully accounted: nothing. Student 3 paid in a later month: not yet.
    assert 2 not in by_student and 3 not in by_student
    # Student 4's October money disappeared (refund or reversal): a negative correction.
    assert by_student[4].kind == calc.CORRECTION
    assert (by_student[4].base, by_student[4].amount) == (-200_000, -100_000)
    assert all(line.teacher_id == 7 for line in lines)


def test_rate_per_teacher_and_rounding():
    lines = calc.draft_lines(
        NOV, {(1, 10, NOV): 333_333}, {}, {10: 8}, rate_for({8: 6500}), percent_of
    )
    assert lines[0].rate_bp == 6500
    assert lines[0].amount == 216_666  # 216 666,45 rounded half-up to whole so'm


def test_rate_on_takes_latest_row_on_or_before_month():
    rows = [
        calc.RateRow(OCT, (1,), 5000),
        calc.RateRow(DEC, (2,), 6500),
        calc.RateRow(OCT, (3,), 5500),  # same month, created later: wins
    ]
    assert calc.rate_on(rows, D(2026, 9, 1), 4000) == 4000
    assert calc.rate_on(rows, NOV, 4000) == 5500
    assert calc.rate_on(rows, DEC, 4000) == 6500


def test_totals():
    lines = calc.draft_lines(
        NOV,
        {(1, 10, NOV): 400_000, (2, 10, OCT): 100_000},
        {(2, 10, OCT): 300_000},
        {10: 7},
        rate_for({}),
        percent_of,
    )
    t = calc.totals(lines, [("bonus", 50_000), ("deduction", -20_000), ("carry", -5_000)])
    assert (t.paid, t.share, t.corrections) == (400_000, 200_000, -100_000)
    assert (t.bonuses, t.deductions, t.total) == (50_000, -25_000, 125_000)


def test_percent_text():
    assert parse_percent("50") == 5000
    assert parse_percent("62,5") == 6250
    assert parse_percent(" 65 % ") == 6500
    assert format_percent(6250) == "62,5"
    assert format_percent(5000) == "50"
    for bad in ("", "abc", "1,234", "-5"):
        try:
            parse_percent(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
