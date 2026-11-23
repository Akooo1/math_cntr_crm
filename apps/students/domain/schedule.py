"""Lesson calendar math. Pure functions, no Django."""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Slot:
    weekday: int  # 1 = Monday ... 7 = Sunday (ISO)
    start_time: dt.time
    end_time: dt.time
    room_id: int | None = None


@dataclass(frozen=True)
class PlannedLesson:
    date: dt.date
    start_time: dt.time
    end_time: dt.time
    room_id: int | None


def lesson_plan(slots: Iterable[Slot], start: dt.date, end: dt.date) -> list[PlannedLesson]:
    """All lessons from `start` to `end` inclusive, ordered by date and time."""
    by_day: dict[int, list[Slot]] = {}
    for slot in slots:
        by_day.setdefault(slot.weekday, []).append(slot)
    out = []
    day = start
    while day <= end:
        for slot in sorted(by_day.get(day.isoweekday(), []), key=lambda s: s.start_time):
            out.append(PlannedLesson(day, slot.start_time, slot.end_time, slot.room_id))
        day += dt.timedelta(days=1)
    return out


def is_active_on(start: dt.date, end: dt.date | None, day: dt.date) -> bool:
    """Enrollment window is [start, end): `end` is the first day not attending."""
    return start <= day and (end is None or day < end)


def is_frozen_on(freezes: Iterable[tuple[dt.date, dt.date | None]], day: dt.date) -> bool:
    return any(is_active_on(f, t, day) for f, t in freezes)
