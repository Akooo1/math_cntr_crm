import dataclasses
import datetime as dt

from apps.core.events import DomainEvent


@dataclasses.dataclass(frozen=True)
class StaffCheckedIn(DomainEvent):
    name = "staff.checked_in"

    user_id: int
    branch_id: int
    date: dt.date
    time: str  # HH:MM, Tashkent
    late_minutes: int
    source: str
