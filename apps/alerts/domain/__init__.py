"""Early-warning rules (docs/SPEC.md §19). Pure Python: no Django, no database."""

import datetime as dt


def response_deadline(
    created: dt.datetime, hours: int, start_hour: int, end_hour: int
) -> dt.datetime:
    """When a lead created at `created` (local, naive) must have been contacted: `hours` of
    working time counted only between `start_hour` and `end_hour` every day.

    A lead that arrives at 21:00 with a 2-hour deadline and 09–19 working hours is due at
    11:00 the next morning.
    """
    if not (0 <= start_hour < end_hour <= 24):
        raise ValueError("working hours")
    remaining = dt.timedelta(hours=hours)

    def day_start(d: dt.date) -> dt.datetime:
        return dt.datetime.combine(d, dt.time(start_hour))

    def day_end(d: dt.date) -> dt.datetime:
        return dt.datetime.combine(d, dt.time()) + dt.timedelta(hours=end_hour)

    cursor = created
    if cursor < day_start(cursor.date()):
        cursor = day_start(cursor.date())
    elif cursor >= day_end(cursor.date()):
        cursor = day_start(cursor.date() + dt.timedelta(days=1))
    while True:
        available = day_end(cursor.date()) - cursor
        if remaining <= available:
            return cursor + remaining
        remaining -= available
        cursor = day_start(cursor.date() + dt.timedelta(days=1))


def absence_streak(marks_newest_first: list[tuple[int, str]]) -> tuple[int, int | None]:
    """[(lesson_id, "present" | "absent"), ...] newest first -> (missed in a row now, the
    first lesson of that run). (0, None) when the last mark is "present"."""
    run: list[int] = []
    for lesson_id, status in marks_newest_first:
        if status != "absent":
            break
        run.append(lesson_id)
    return (len(run), run[-1] if run else None)


def debt_round(days_overdue: int, first_after: int, repeat_every: int) -> int | None:
    """Which reminder round a debt is in: None = too early, 0 = first task, 1, 2 ... = a
    repeat every `repeat_every` days (0 = never repeat)."""
    if first_after <= 0 or days_overdue < first_after:
        return None
    if repeat_every <= 0:
        return 0
    return (days_overdue - first_after) // repeat_every
