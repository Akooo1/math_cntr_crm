import dataclasses

from apps.core.events import DomainEvent


@dataclasses.dataclass(frozen=True)
class LeadCreated(DomainEvent):
    name = "crm.lead_created"

    lead_id: int
    branch_id: int


@dataclasses.dataclass(frozen=True)
class TrialLessonBooked(DomainEvent):
    name = "crm.trial_lesson_booked"

    lead_id: int
    trial_id: int
    scheduled_date: str


@dataclasses.dataclass(frozen=True)
class LeadConverted(DomainEvent):
    name = "crm.lead_converted"

    lead_id: int
    student_id: int
    branch_id: int
