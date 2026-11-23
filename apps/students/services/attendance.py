"""Attendance marks (informational only in module 1; no billing effect)."""

import datetime as dt

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit, dates, events
from apps.core.permissions import ensure_branch_access, require_perm
from apps.core.roles import Role
from apps.core.system_settings import get_setting

from ..events import LessonHeld
from ..models import Attendance, Lesson
from ..selectors import roster


def can_mark(user, lesson: Lesson) -> bool:
    today = dates.today()
    if lesson.status == Lesson.Status.CANCELLED or lesson.date > today:
        return False
    if user.role == Role.TEACHER:
        if lesson.group.teacher_id != user.pk:
            return False
        window = get_setting("students.attendance_edit_days")
        return today - lesson.date <= dt.timedelta(days=window)
    return True


def mark_attendance(*, actor, lesson: Lesson, student_id: int, status: str) -> Attendance:
    require_perm(actor, "attendance.mark")
    ensure_branch_access(actor, lesson.group.branch_id)
    if actor.role == Role.TEACHER and lesson.group.teacher_id != actor.pk:
        raise PermissionDenied
    if status not in Attendance.Status.values:
        raise ValidationError(_("Unknown status."))
    if not can_mark(actor, lesson):
        raise ValidationError(_("Attendance for this lesson can no longer be changed."))
    enrollment = next((e for e in roster(lesson) if e.student_id == student_id), None)
    if enrollment is None:
        raise ValidationError(_("The student is not in this group on this date."))
    with transaction.atomic():
        lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
        row = Attendance.objects.filter(lesson=lesson, student_id=student_id).first()
        if row is None:
            row = Attendance.objects.create(
                lesson=lesson,
                enrollment=enrollment,
                student_id=student_id,
                status=status,
                marked_by=actor,
            )
        elif row.status != status:
            before = audit.snapshot(row)
            row.status = status
            row.marked_by = actor
            row.save(update_fields=["status", "marked_by", "marked_at"])
            audit.record(
                actor,
                "students.attendance.update",
                row,
                before=before,
                after=audit.snapshot(row),
                branch_id=lesson.group.branch_id,
            )
        if lesson.status == Lesson.Status.SCHEDULED:
            lesson.status = Lesson.Status.HELD
            lesson.save(update_fields=["status"])
            events.publish(
                LessonHeld(
                    lesson_id=lesson.pk,
                    group_id=lesson.group_id,
                    teacher_id=lesson.group.teacher_id,
                )
            )
    return row
