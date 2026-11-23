"""Check-in rules (docs/SPEC.md §14). Pure Python."""

import datetime as dt
import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000
MAX_ACCURACY_M = 200


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Great-circle distance in whole metres (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * EARTH_RADIUS_M * math.asin(math.sqrt(a)))


@dataclass(frozen=True)
class Place:
    branch_id: int
    latitude: float
    longitude: float
    radius_m: int


@dataclass(frozen=True)
class Match:
    place: Place
    distance_m: int

    @property
    def inside(self) -> bool:
        return self.distance_m <= self.place.radius_m


def nearest(places: list[Place], latitude: float, longitude: float) -> Match | None:
    best = None
    for place in places:
        d = distance_m(latitude, longitude, place.latitude, place.longitude)
        if best is None or d < best.distance_m:
            best = Match(place, d)
    return best


def late_minutes(start: dt.time | None, arrived: dt.time, grace: int) -> int:
    """Minutes after the start time, or 0 when within the grace period or unscheduled."""
    if start is None:
        return 0
    minutes = (arrived.hour * 60 + arrived.minute) - (start.hour * 60 + start.minute)
    return minutes if minutes > grace else 0


def works_on(workdays: list[int] | None, day: dt.date) -> bool:
    return bool(workdays) and day.isoweekday() in workdays


def status(*, scheduled: bool, works_today: bool, checked_in: bool, late: int) -> str:
    """on_time | late | not_yet | day_off | no_schedule"""
    if checked_in:
        return "late" if late else "on_time"
    if not scheduled:
        return "no_schedule"
    return "not_yet" if works_today else "day_off"
