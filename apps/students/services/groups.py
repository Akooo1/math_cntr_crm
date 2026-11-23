"""Groups, weekly schedule and the lesson calendar."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit, dates
from apps.core.permissions import ensure_branch_access, require_perm
from apps.core.roles import Role

from ..domain.schedule import Slot, lesson_plan
from ..models import Group, Lesson, ScheduleSlot

HORIZON_DAYS = 90  # open-ended groups get lessons this far ahead (rolled daily)


def _slots_snapshot(group) -> list[str]:
    return [
        f"{s.weekday} {s.start_time:%H:%M}-{s.end_time:%H:%M} {s.room_id or ''}".strip()
        for s in group.slots.order_by("weekday", "start_time")
    ]


def _validate(group: Group, slots: list[dict]):
    if group.teacher.role != Role.TEACHER or group.branch_id not in group.teacher.branch_ids:
        raise ValidationError(_("The teacher must work in the group's branch."))
    if group.room_id and group.room.branch_id != group.branch_id:
        raise ValidationError(_("The room must be in the group's branch."))
    if not slots:
        raise ValidationError(_("Add at least one lesson to the weekly schedule."))
    for s in slots:
        if s["end_time"] <= s["start_time"]:
            raise ValidationError(_("The lesson must end after it starts."))
        room = s.get("room")
        if room is not None and room.branch_id != group.branch_id:
            raise ValidationError(_("The room must be in the group's branch."))


def save_group(*, actor, group: Group, slots: list[dict], import_batch=None) -> Group:
    """Create or update a group with its weekly schedule, then (re)build future lessons."""
    require_perm(actor, "groups.manage")
    ensure_branch_access(actor, group.branch_id)
    _validate(group, slots)
    with transaction.atomic():
        before = None
        if group.pk:
            fresh = Group.objects.get(pk=group.pk)
            ensure_branch_access(actor, fresh.branch_id)
            if fresh.branch_id != group.branch_id:
                raise ValidationError(_("A group can't move to another branch."))
            before = audit.snapshot(fresh, {"schedule": _slots_snapshot(fresh)})
        if import_batch is not None:
            group.import_batch = import_batch
        group.save()
        group.slots.all().delete()
        ScheduleSlot.objects.bulk_create(
            ScheduleSlot(
                group=group,
                weekday=s["weekday"],
                start_time=s["start_time"],
                end_time=s["end_time"],
                room=s.get("room"),
            )
            for s in slots
        )
        after = audit.snapshot(group, {"schedule": _slots_snapshot(group)})
        audit.record(
            actor,
            f"students.group.{'update' if before else 'create'}",
            group,
            before=before,
            after=after,
        )
        generate_lessons(group)
    return group


def _horizon(group: Group) -> dt.date:
    if group.end_date:
        return group.end_date
    return max(dates.today(), group.start_date) + dt.timedelta(days=HORIZON_DAYS)


def generate_lessons(group: Group) -> int:
    """Make the lesson rows match the schedule. Idempotent.

    The first run (a new or imported group) also creates past lessons from the start date.
    Later runs (schedule changes) only add lessons from today on: the past is history.
    Lessons that already happened, have attendance or were cancelled by hand are never
    touched. Returns the number of lessons created.
    """
    if group.status == Group.Status.FINISHED:
        return 0
    today = dates.today()
    slots = [
        Slot(s.weekday, s.start_time, s.end_time, s.room_id or group.room_id)
        for s in group.slots.all()
    ]
    plan = lesson_plan(slots, group.start_date, _horizon(group))
    wanted = {(p.date, p.start_time): p for p in plan}
    existing = {(lesson.date, lesson.start_time): lesson for lesson in group.lessons.all()}
    first_run = not existing
    stale = [
        lesson.pk
        for key, lesson in existing.items()
        if key not in wanted
        and lesson.date >= today
        and lesson.status == Lesson.Status.SCHEDULED
        and not lesson.attendance.exists()
    ]
    Lesson.objects.filter(pk__in=stale).delete()
    new = [
        Lesson(
            group=group,
            date=p.date,
            start_time=p.start_time,
            end_time=p.end_time,
            room_id=p.room_id,
        )
        for key, p in wanted.items()
        if key not in existing and (first_run or p.date >= today)
    ]
    Lesson.objects.bulk_create(new)
    return len(new)


def _lesson_for_update(actor, lesson):
    require_perm(actor, "groups.manage")
    ensure_branch_access(actor, lesson.group.branch_id)
    return Lesson.objects.select_for_update().get(pk=lesson.pk)


def cancel_lesson(*, actor, lesson: Lesson, reason: str) -> Lesson:
    """Holiday, teacher ill... Cancelled lessons don't count for proration (SPEC 6.3)."""
    if not reason.strip():
        raise ValidationError(_("Write the reason."))
    with transaction.atomic():
        lesson = _lesson_for_update(actor, lesson)
        if lesson.attendance.exists():
            raise ValidationError(_("Attendance is already marked for this lesson."))
        before = audit.snapshot(lesson)
        lesson.status = Lesson.Status.CANCELLED
        lesson.cancel_reason = reason.strip()
        lesson.save(update_fields=["status", "cancel_reason"])
        audit.record(
            actor,
            "students.lesson.cancel",
            lesson,
            before=before,
            after=audit.snapshot(lesson),
            branch_id=lesson.group.branch_id,
            reason=lesson.cancel_reason,
        )
    return lesson


def restore_lesson(*, actor, lesson: Lesson) -> Lesson:
    with transaction.atomic():
        lesson = _lesson_for_update(actor, lesson)
        before = audit.snapshot(lesson)
        lesson.status = Lesson.Status.SCHEDULED
        lesson.cancel_reason = ""
        lesson.save(update_fields=["status", "cancel_reason"])
        audit.record(
            actor,
            "students.lesson.restore",
            lesson,
            before=before,
            after=audit.snapshot(lesson),
            branch_id=lesson.group.branch_id,
        )
    return lesson
