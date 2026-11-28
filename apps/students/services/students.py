"""Student records."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit, events
from apps.core.permissions import accessible_branch_ids, ensure_branch_access, require_perm

from ..events import StudentCreated
from ..models import Student

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


def _clean(data: dict) -> dict:
    out = {k: data.get(k) for k in FIELDS}
    for k, v in out.items():
        if v is None and k != "birth_date":
            out[k] = ""
    if not out["phone"] and not out["parent_phone"]:
        raise ValidationError(_("Enter the student's or the parent's phone."))
    return out


def _refuse_taken_phone(actor, phone: str, exclude_id=None) -> None:
    """A student's own phone belongs to one student (owner's request, SPEC §24)."""
    from .. import selectors

    owner = selectors.own_phone_owner(phone, exclude_id)
    if owner is None:
        return
    allowed = accessible_branch_ids(actor)
    if allowed is None or owner.branch_id in allowed:
        raise ValidationError(
            _("This student is already registered: %(name)s (%(branch)s).")
            % {"name": owner.full_name, "branch": owner.branch.name}
        )
    raise ValidationError(
        _("A student with this phone is already registered in another branch: %(branch)s.")
        % {"branch": owner.branch.name}
    )


def create_student(*, actor, branch, data: dict, lead=None, import_batch=None) -> Student:
    """Create a student in `branch`. `data` holds already-validated, normalized values."""
    require_perm(actor, "students.create")
    ensure_branch_access(actor, branch.pk)
    values = _clean(data)
    with transaction.atomic():
        _refuse_taken_phone(actor, values["phone"])
        student = Student.objects.create(
            branch=branch, lead=lead, import_batch=import_batch, **values
        )
        audit.record(actor, "students.student.create", student, after=audit.snapshot(student))
        events.publish(StudentCreated(student_id=student.pk, branch_id=branch.pk))
    return student


def update_student(*, actor, student: Student, data: dict) -> Student:
    require_perm(actor, "students.manage")
    ensure_branch_access(actor, student.branch_id)
    values = _clean(data)
    with transaction.atomic():
        student = Student.objects.select_for_update().get(pk=student.pk)
        if values["phone"] != student.phone:  # old duplicates stay editable
            _refuse_taken_phone(actor, values["phone"], exclude_id=student.pk)
        before = audit.snapshot(student)
        for k, v in values.items():
            setattr(student, k, v)
        student.save()
        audit.record(
            actor, "students.student.update", student, before=before, after=audit.snapshot(student)
        )
    return student
