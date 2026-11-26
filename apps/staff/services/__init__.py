"""Staff check-in writes (docs/SPEC.md §14). Every write is audited."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit, dates
from apps.core.events import publish
from apps.core.permissions import ensure_branch_access, require_perm
from apps.core.roles import Role
from apps.core.system_settings import get_setting
from apps.settings.models import Branch

from ..domain import rules
from ..events import StaffCheckedIn
from ..models import BranchLocation, CheckIn, Schedule


def _expected(user, day: dt.date) -> dt.time | None:
    """Teachers: the start of their first lesson that day (no lessons = day off). Others:
    their working-time schedule."""
    from .. import selectors

    return selectors.expected_start(user, day)


def _create(*, user, branch_id: int, at: dt.datetime, actor, **fields) -> CheckIn:
    day = timezone.localtime(at).date()
    expected = _expected(user, day)
    late = rules.late_minutes(
        expected, timezone.localtime(at).time(), get_setting("staff.grace_minutes")
    )
    try:
        with transaction.atomic():
            checkin = CheckIn.objects.create(
                user=user,
                branch_id=branch_id,
                date=day,
                checked_in_at=at,
                expected_start=expected,
                late_minutes=late,
                created_by=actor,
                **fields,
            )
    except IntegrityError:
        raise ValidationError(_("The arrival for this day is already recorded.")) from None
    audit.record(
        actor,
        "staff.checkin.create",
        checkin,
        after=audit.snapshot(checkin),
        branch_id=branch_id,
        reason=fields.get("reason", ""),
    )
    publish(
        StaffCheckedIn(
            user_id=user.pk,
            branch_id=branch_id,
            date=day,
            time=f"{timezone.localtime(at):%H:%M}",
            late_minutes=late,
            source=checkin.source,
        )
    )
    return checkin


def check_in(
    *, actor, latitude: float, longitude: float, accuracy_m: float, ip=None, user_agent=""
) -> CheckIn:
    """The employee's own "Keldim": within the radius of one of their branches."""
    require_perm(actor, "staff.checkin")
    if accuracy_m is None or accuracy_m > rules.MAX_ACCURACY_M:
        raise ValidationError(
            _("The location is not precise enough. Go near a window or outside and try again.")
        )
    places = [
        rules.Place(loc.branch_id, loc.latitude, loc.longitude, loc.radius_m)
        for loc in BranchLocation.objects.filter(
            branch_id__in=actor.branch_ids, branch__is_active=True
        )
    ]
    if not places:
        raise ValidationError(_("Your branch's location is not set yet. Tell the Direktor."))
    match = rules.nearest(places, latitude, longitude)
    if not match.inside:
        branch = Branch.objects.get(pk=match.place.branch_id)
        raise ValidationError(
            _("You are %(d)s m from %(branch)s. Mark your arrival within %(r)s m.")
            % {"d": match.distance_m, "branch": branch.name, "r": match.place.radius_m}
        )
    with transaction.atomic():
        return _create(
            user=actor,
            branch_id=match.place.branch_id,
            at=dates.now(),
            actor=actor,
            source=CheckIn.Source.GPS,
            latitude=latitude,
            longitude=longitude,
            accuracy_m=round(accuracy_m),
            distance_m=match.distance_m,
            ip=ip,
            user_agent=(user_agent or "")[:300],
        )


def manual_check_in(*, actor, user, branch, day: dt.date, time: dt.time, reason: str) -> CheckIn:
    """The Direktor records an arrival by hand (GPS failed, phone dead)."""
    require_perm(actor, "staff.attendance.view")
    if user.role == Role.DIRECTOR:
        raise ValidationError(_("The Direktor doesn't mark arrival."))
    if branch.pk not in user.branch_ids:
        raise ValidationError(_("The employee doesn't work in this branch."))
    if not reason.strip():
        raise ValidationError(_("Write the reason."))
    at = timezone.make_aware(dt.datetime.combine(day, time))
    if at > dates.now():
        raise ValidationError(_("The time can't be in the future."))
    with transaction.atomic():
        return _create(
            user=user,
            branch_id=branch.pk,
            at=at,
            actor=actor,
            source=CheckIn.Source.MANUAL,
            reason=reason.strip(),
        )


def save_location(*, actor, branch, latitude: float, longitude: float, radius_m: int):
    require_perm(actor, "settings.manage")
    ensure_branch_access(actor, branch.pk)
    with transaction.atomic():
        loc = BranchLocation.objects.filter(branch=branch).first()
        before = audit.snapshot(loc)
        if loc is None:
            loc = BranchLocation(branch=branch)
        loc.latitude, loc.longitude, loc.radius_m, loc.updated_by = (
            latitude,
            longitude,
            radius_m,
            actor,
        )
        loc.full_clean(exclude=["branch", "updated_by"])
        loc.save()
        audit.record(
            actor,
            "staff.location.update",
            loc,
            before=before,
            after=audit.snapshot(loc),
            branch_id=branch.pk,
        )
    return loc


def save_schedule(*, actor, user, start_time: dt.time | None, workdays: list[int]):
    if user.role == Role.TEACHER:
        raise ValidationError(_("A teacher's arrival time comes from their lesson schedule."))
    """Start time and workdays; no start time removes the schedule (no lateness)."""
    require_perm(actor, "settings.manage")
    if user.role == Role.DIRECTOR:
        raise ValidationError(_("The Direktor doesn't mark arrival."))
    workdays = sorted({int(d) for d in workdays if 1 <= int(d) <= 7})
    with transaction.atomic():
        schedule = Schedule.objects.filter(user=user).first()
        before = audit.snapshot(schedule)
        if start_time is None:
            if schedule is not None:
                audit.record(actor, "staff.schedule.update", schedule, before=before, after={})
                schedule.delete()
            return None
        if not workdays:
            raise ValidationError(_("Choose at least one workday."))
        if schedule is None:
            schedule = Schedule(user=user)
        schedule.start_time, schedule.workdays, schedule.updated_by = start_time, workdays, actor
        schedule.save()
        audit.record(
            actor,
            "staff.schedule.update",
            schedule,
            before=before,
            after=audit.snapshot(schedule),
        )
    return schedule
