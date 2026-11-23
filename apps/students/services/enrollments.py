"""Enrollment lifecycle: enroll, move, freeze, unfreeze, leave (docs/SPEC.md 6.3).

Every action records an effective date and a reason, writes an enrollment event and an
audit row, publishes a domain event and lets registered extensions (billing) act inside the
same transaction.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit, events
from apps.core.permissions import ensure_branch_access, require_perm

from .. import extensions
from ..events import (
    EnrollmentCreated,
    EnrollmentFrozen,
    EnrollmentLeft,
    EnrollmentMoved,
    EnrollmentUnfrozen,
)
from ..extensions import ActionResult, EnrollmentAction
from ..models import Enrollment, EnrollmentEvent, Freeze, Group, Student

Status = Enrollment.Status
Kind = EnrollmentEvent.Kind


def _check(actor, branch_id):
    require_perm(actor, "students.manage")
    ensure_branch_access(actor, branch_id)


def _need_reason(reason: str) -> str:
    if not (reason or "").strip():
        raise ValidationError(_("Write the reason."))
    return reason.strip()


def _lock_enrollment(enrollment) -> Enrollment:
    return (
        Enrollment.objects.select_for_update()
        .select_related("group", "student")
        .get(pk=enrollment.pk)
    )


def open_seats(group: Group) -> int:
    taken = group.enrollments.filter(status__in=Enrollment.OPEN).count()
    return group.capacity - taken


def _check_group(group: Group, student: Student, day, *, capacity_override: bool):
    if group.branch_id != student.branch_id:
        raise ValidationError(_("The group is in another branch."))
    if group.status == Group.Status.FINISHED:
        raise ValidationError(_("The group has finished."))
    if day < group.start_date:
        raise ValidationError(_("The date is before the group starts."))
    if group.end_date and day >= group.end_date:
        raise ValidationError(_("The date is after the group ends."))
    if Enrollment.objects.filter(student=student, group=group, status__in=Enrollment.OPEN).exists():
        raise ValidationError(_("The student is already in this group."))
    if open_seats(group) <= 0 and not capacity_override:
        raise ValidationError(_("The group is full. Tick 'Over capacity' to enroll anyway."))


def _event(enrollment, kind, day, reason, actor, related=None):
    return EnrollmentEvent.objects.create(
        enrollment=enrollment,
        kind=kind,
        effective_date=day,
        reason=reason,
        related_enrollment=related,
        created_by=actor,
    )


def _audit(actor, verb, enrollment, before, reason, extra=None):
    after = audit.snapshot(enrollment, extra)
    audit.record(
        actor,
        f"students.enrollment.{verb}",
        enrollment,
        before=before,
        after=after,
        branch_id=enrollment.group.branch_id,
        reason=reason,
        only_changes=before is not None,
    )


def _run_extensions(action, data, actor, result, skip):
    if skip:
        return
    for ext in extensions.all_extensions():
        if data is not None:
            errors = ext.validate(action, data)
            if errors:
                raise ValidationError(errors)
        ext.apply(action, data, actor=actor, result=result)


def enroll(
    *,
    actor,
    student: Student,
    group: Group,
    start_date,
    reason: str = "",
    capacity_override: bool = False,
    extension_data=None,
    skip_extensions: bool = False,
    import_batch=None,
) -> Enrollment:
    _check(actor, student.branch_id)
    ensure_branch_access(actor, group.branch_id)
    with transaction.atomic():
        group = Group.objects.select_for_update().get(pk=group.pk)
        _check_group(group, student, start_date, capacity_override=capacity_override)
        enrollment = Enrollment.objects.create(
            student=student, group=group, start_date=start_date, import_batch=import_batch
        )
        _event(enrollment, Kind.ENROLLED, start_date, reason, actor)
        over = open_seats(group) < 0
        _audit(actor, "create", enrollment, None, reason, {"over_capacity": over} if over else None)
        action = EnrollmentAction("enroll", student, start_date, group=group)
        _run_extensions(
            action, extension_data, actor, ActionResult(enrollment=enrollment), skip_extensions
        )
        events.publish(
            EnrollmentCreated(
                enrollment_id=enrollment.pk,
                student_id=student.pk,
                group_id=group.pk,
                start_date=start_date,
            )
        )
    return enrollment


def move(
    *,
    actor,
    enrollment: Enrollment,
    target_group: Group,
    effective_date,
    reason: str,
    capacity_override: bool = False,
    extension_data=None,
) -> Enrollment:
    """Close the old enrollment as 'moved' and open a new one on the same date."""
    _check(actor, enrollment.group.branch_id)
    reason = _need_reason(reason)
    with transaction.atomic():
        old = _lock_enrollment(enrollment)
        if old.status != Status.ACTIVE:
            raise ValidationError(_("Only an active enrollment can be moved."))
        if target_group.pk == old.group_id:
            raise ValidationError(_("Choose another group."))
        if effective_date < old.start_date:
            raise ValidationError(_("The date is before the student joined the group."))
        target = Group.objects.select_for_update().get(pk=target_group.pk)
        _check_group(target, old.student, effective_date, capacity_override=capacity_override)
        before = audit.snapshot(old)
        old.status = Status.MOVED
        old.end_date = effective_date
        old.save(update_fields=["status", "end_date"])
        new = Enrollment.objects.create(
            student=old.student, group=target, start_date=effective_date
        )
        _event(old, Kind.MOVED_OUT, effective_date, reason, actor, related=new)
        _event(new, Kind.MOVED_IN, effective_date, reason, actor, related=old)
        _audit(actor, "move", old, before, reason, {"new_group": target.pk})
        action = EnrollmentAction("move", old.student, effective_date, group=target, enrollment=old)
        _run_extensions(
            action, extension_data, actor, ActionResult(enrollment=new, closed=old), False
        )
        events.publish(
            EnrollmentMoved(
                old_enrollment_id=old.pk,
                new_enrollment_id=new.pk,
                student_id=old.student_id,
                effective_date=effective_date,
            )
        )
    return new


def freeze(
    *, actor, enrollment: Enrollment, from_date, reason: str, extension_data=None
) -> Enrollment:
    _check(actor, enrollment.group.branch_id)
    reason = _need_reason(reason)
    with transaction.atomic():
        e = _lock_enrollment(enrollment)
        if e.status != Status.ACTIVE:
            raise ValidationError(_("Only an active enrollment can be frozen."))
        if from_date < e.start_date:
            raise ValidationError(_("The date is before the student joined the group."))
        before = audit.snapshot(e)
        e.status = Status.FROZEN
        e.save(update_fields=["status"])
        Freeze.objects.create(enrollment=e, from_date=from_date, reason=reason)
        _event(e, Kind.FROZEN, from_date, reason, actor)
        _audit(actor, "freeze", e, before, reason, {"from_date": from_date})
        action = EnrollmentAction("freeze", e.student, from_date, enrollment=e)
        _run_extensions(action, extension_data, actor, ActionResult(enrollment=e), False)
        events.publish(EnrollmentFrozen(enrollment_id=e.pk, from_date=from_date))
    return e


def unfreeze(*, actor, enrollment: Enrollment, effective_date, reason: str, extension_data=None):
    """`effective_date` is the first day the student attends again."""
    _check(actor, enrollment.group.branch_id)
    reason = _need_reason(reason)
    with transaction.atomic():
        e = _lock_enrollment(enrollment)
        if e.status != Status.FROZEN:
            raise ValidationError(_("The enrollment is not frozen."))
        open_freeze = e.freezes.select_for_update().filter(to_date__isnull=True).first()
        if open_freeze and effective_date <= open_freeze.from_date:
            raise ValidationError(_("The date must be after the freeze started."))
        before = audit.snapshot(e)
        e.status = Status.ACTIVE
        e.save(update_fields=["status"])
        if open_freeze:
            open_freeze.to_date = effective_date
            open_freeze.save(update_fields=["to_date"])
        _event(e, Kind.UNFROZEN, effective_date, reason, actor)
        _audit(actor, "unfreeze", e, before, reason, {"to_date": effective_date})
        action = EnrollmentAction(
            "unfreeze", e.student, effective_date, group=e.group, enrollment=e
        )
        _run_extensions(action, extension_data, actor, ActionResult(enrollment=e), False)
        events.publish(EnrollmentUnfrozen(enrollment_id=e.pk, effective_date=effective_date))
    return e


def leave(*, actor, enrollment: Enrollment, end_date, reason: str, extension_data=None):
    """`end_date` is the first day the student no longer attends."""
    _check(actor, enrollment.group.branch_id)
    reason = _need_reason(reason)
    with transaction.atomic():
        e = _lock_enrollment(enrollment)
        if e.status not in Enrollment.OPEN:
            raise ValidationError(_("The student is no longer in this group."))
        if end_date < e.start_date:
            raise ValidationError(_("The date is before the student joined the group."))
        before = audit.snapshot(e)
        e.status = Status.LEFT
        e.end_date = end_date
        e.save(update_fields=["status", "end_date"])
        e.freezes.filter(to_date__isnull=True).update(to_date=max(end_date, e.start_date))
        _event(e, Kind.LEFT, end_date, reason, actor)
        _audit(actor, "leave", e, before, reason)
        action = EnrollmentAction("leave", e.student, end_date, group=e.group, enrollment=e)
        _run_extensions(action, extension_data, actor, ActionResult(enrollment=e), False)
        events.publish(EnrollmentLeft(enrollment_id=e.pk, end_date=end_date))
    return e
