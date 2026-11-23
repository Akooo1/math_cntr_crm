import dataclasses
import datetime as dt

from apps.core.events import DomainEvent


@dataclasses.dataclass(frozen=True)
class StudentCreated(DomainEvent):
    name = "students.student_created"

    student_id: int
    branch_id: int


@dataclasses.dataclass(frozen=True)
class EnrollmentCreated(DomainEvent):
    name = "students.enrollment_created"

    enrollment_id: int
    student_id: int
    group_id: int
    start_date: dt.date


@dataclasses.dataclass(frozen=True)
class EnrollmentMoved(DomainEvent):
    name = "students.enrollment_moved"

    old_enrollment_id: int
    new_enrollment_id: int
    student_id: int
    effective_date: dt.date


@dataclasses.dataclass(frozen=True)
class EnrollmentFrozen(DomainEvent):
    name = "students.enrollment_frozen"

    enrollment_id: int
    from_date: dt.date


@dataclasses.dataclass(frozen=True)
class EnrollmentUnfrozen(DomainEvent):
    name = "students.enrollment_unfrozen"

    enrollment_id: int
    effective_date: dt.date


@dataclasses.dataclass(frozen=True)
class EnrollmentLeft(DomainEvent):
    name = "students.enrollment_left"

    enrollment_id: int
    end_date: dt.date


@dataclasses.dataclass(frozen=True)
class LessonHeld(DomainEvent):
    """First attendance mark on a lesson. A future salary module can count these."""

    name = "students.lesson_held"

    lesson_id: int
    group_id: int
    teacher_id: int
