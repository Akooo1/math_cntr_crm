"""Writes for students. Phase 2: create a student (used by lead conversion)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit, events
from apps.core.permissions import ensure_branch_access, require_perm

from .events import StudentCreated
from .models import Student

FIELDS = (
    "first_name",
    "last_name",
    "middle_name",
    "birth_date",
    "phone",
    "parent_name",
    "parent_phone",
    "extra_phone",
    "notes",
)


def create_student(*, actor, branch, data: dict, lead=None) -> Student:
    """Create a student in `branch`. `data` holds already-validated, normalized values."""
    require_perm(actor, "students.create")
    ensure_branch_access(actor, branch.pk)
    if not data.get("phone") and not data.get("parent_phone"):
        raise ValidationError(_("Enter the student's or the parent's phone."))
    with transaction.atomic():
        student = Student.objects.create(
            branch=branch, lead=lead, **{k: data.get(k) or _default(k) for k in FIELDS}
        )
        audit.record(actor, "students.student.create", student, after=audit.snapshot(student))
        events.publish(StudentCreated(student_id=student.pk, branch_id=branch.pk))
    return student


def _default(field: str):
    return None if field == "birth_date" else ""
