import dataclasses

from apps.core.events import DomainEvent


@dataclasses.dataclass(frozen=True)
class StudentCreated(DomainEvent):
    name = "students.student_created"

    student_id: int
    branch_id: int
