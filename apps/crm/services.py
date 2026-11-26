"""CRM writes (docs/SPEC.md 6.2). Every function checks permission and branch scope.

Lead history lives in crm_lead_activity. The audit log records the conversion, because it
creates a student.
"""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit, dates, events
from apps.core.permissions import ensure_branch_access, require_perm
from apps.students import services as student_services
from apps.students.models import Lesson

from . import selectors
from .events import LeadConverted, LeadCreated, TrialLessonBooked
from .models import FollowUpTask, Lead, LeadActivity, LeadStage, TrialLesson

Kind = LeadStage.Kind


class DuplicateWarning(ValidationError):
    """Raised when the phone already exists and the user has not confirmed saving anyway."""

    def __init__(self, duplicates):
        self.duplicates = duplicates
        super().__init__(_("This phone number already exists. Check before saving."))


def _digits(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())


def _log(lead, actor, kind, text="", from_stage=None, to_stage=None):
    return LeadActivity.objects.create(
        lead=lead, kind=kind, text=text, from_stage=from_stage, to_stage=to_stage, created_by=actor
    )


def _lock(lead: Lead) -> Lead:
    return Lead.objects.select_for_update().select_related("stage").get(pk=lead.pk)


def _check_manager(manager, branch_id):
    if manager is None:
        return
    if not selectors.branch_staff([branch_id]).filter(pk=manager.pk).exists():
        raise ValidationError(_("The manager must work in the lead's branch."))


def _check_duplicates(actor, phones, confirm, exclude_lead_id=None):
    dups = selectors.find_duplicates(actor, phones, exclude_lead_id=exclude_lead_id)
    if dups and not confirm:
        raise DuplicateWarning(dups)
    return dups


def _refresh_follow_up(lead: Lead) -> None:
    first = lead.tasks.filter(done_at__isnull=True).order_by("due_at").first()
    Lead.objects.filter(pk=lead.pk).update(next_follow_up_at=first.due_at if first else None)


# --- Create / edit ------------------------------------------------------------------


def create_lead(*, actor, branch, data: dict, confirm_duplicate=False) -> Lead:
    require_perm(actor, "crm.leads.edit")
    ensure_branch_access(actor, branch.pk)
    _check_manager(data.get("manager"), branch.pk)
    phones = [data["phone"], data.get("extra_phone") or ""]
    with transaction.atomic():
        _check_duplicates(actor, phones, confirm_duplicate)
        lead = Lead.objects.create(
            branch=branch,
            full_name=data["full_name"].strip(),
            phone=data["phone"],
            phone_normalized=_digits(data["phone"]),
            extra_phone=data.get("extra_phone") or "",
            source=data["source"],
            course=data.get("course"),
            manager=data.get("manager"),
            stage=selectors.stage_of_kind(Kind.NEW),
            notes=data.get("notes") or "",
            created_by=actor,
        )
        _log(lead, actor, LeadActivity.Kind.CREATED, to_stage=lead.stage)
        if data.get("follow_up_at"):
            create_task(
                actor=actor,
                lead=lead,
                assigned_to=lead.manager or actor,
                due_at=data["follow_up_at"],
                title=_("Follow up"),
            )
        events.publish(LeadCreated(lead_id=lead.pk, branch_id=branch.pk))
    return lead


EDITABLE = ("full_name", "phone", "extra_phone", "source", "course", "manager", "notes")


def update_lead(*, actor, lead: Lead, data: dict, confirm_duplicate=False) -> Lead:
    require_perm(actor, "crm.leads.edit")
    ensure_branch_access(actor, lead.branch_id)
    _check_manager(data.get("manager"), lead.branch_id)
    with transaction.atomic():
        lead = _lock(lead)
        new_phones = {data["phone"], data.get("extra_phone") or ""} - {lead.phone, lead.extra_phone}
        if new_phones - {""}:
            _check_duplicates(actor, sorted(new_phones), confirm_duplicate, exclude_lead_id=lead.pk)
        changed = False
        for name in EDITABLE:
            value = data.get(name)
            if name in ("extra_phone", "notes") and value is None:
                value = ""
            if getattr(lead, name) != value:
                setattr(lead, name, value)
                changed = True
        if changed:
            lead.phone_normalized = _digits(lead.phone)
            lead.save()
            _log(lead, actor, LeadActivity.Kind.EDIT)
    return lead


# --- Stages ---------------------------------------------------------------------------


def change_stage(*, actor, lead: Lead, stage: LeadStage) -> Lead:
    """Manual stage move. 'Enrolled' only via conversion; 'Refused' only with a reason."""
    require_perm(actor, "crm.leads.edit")
    ensure_branch_access(actor, lead.branch_id)
    with transaction.atomic():
        lead = _lock(lead)
        if lead.stage_id == stage.pk:
            return lead
        if lead.is_converted:
            raise ValidationError(_("The lead is already a student; its stage can't change."))
        if not stage.is_active:
            raise ValidationError(_("This stage is not active."))
        if stage.kind == Kind.WON:
            raise ValidationError(_("Use 'Convert to student' to enroll a lead."))
        if stage.kind == Kind.LOST:
            raise ValidationError(_("Choose a refusal reason to mark the lead as refused."))
        old = lead.stage
        lead.stage = stage
        if old.kind == Kind.LOST:
            lead.refusal_reason = None
            lead.refusal_note = ""
        lead.save()
        _log(lead, actor, LeadActivity.Kind.STAGE_CHANGE, from_stage=old, to_stage=stage)
    return lead


def refuse(*, actor, lead: Lead, reason, note: str = "") -> Lead:
    require_perm(actor, "crm.leads.edit")
    ensure_branch_access(actor, lead.branch_id)
    if reason is None:
        raise ValidationError(_("Choose a refusal reason."))
    with transaction.atomic():
        lead = _lock(lead)
        if lead.is_converted:
            raise ValidationError(_("The lead is already a student; its stage can't change."))
        old = lead.stage
        lead.stage = selectors.stage_of_kind(Kind.LOST)
        lead.refusal_reason = reason
        lead.refusal_note = note
        lead.save()
        _log(
            lead,
            actor,
            LeadActivity.Kind.STAGE_CHANGE,
            text=note,
            from_stage=old,
            to_stage=lead.stage,
        )
        lead.tasks.filter(done_at__isnull=True).update(done_at=timezone.now(), done_by=actor)
        _refresh_follow_up(lead)
    return lead


def reopen(*, actor, lead: Lead, stage: LeadStage | None = None) -> Lead:
    stage = stage or selectors.stage_of_kind(Kind.CONTACTED)
    lead = Lead.objects.select_related("stage").get(pk=lead.pk)  # never trust a stale copy
    if not lead.is_lost:
        raise ValidationError(_("Only a refused lead can be reopened."))
    return change_stage(actor=actor, lead=lead, stage=stage)


# --- Notes, calls ---------------------------------------------------------------------


def add_activity(*, actor, lead: Lead, kind: str, text: str) -> LeadActivity:
    require_perm(actor, "crm.leads.edit")
    ensure_branch_access(actor, lead.branch_id)
    if kind not in (LeadActivity.Kind.NOTE, LeadActivity.Kind.CALL):
        raise ValidationError(_("Unknown entry type."))
    if not text.strip():
        raise ValidationError(_("Write the text."))
    return _log(lead, actor, kind, text=text.strip())


# --- Tasks ----------------------------------------------------------------------------


def create_task(*, actor, lead: Lead, assigned_to, due_at: dt.datetime, title: str) -> FollowUpTask:
    require_perm(actor, "crm.leads.edit")
    ensure_branch_access(actor, lead.branch_id)
    if assigned_to.pk != actor.pk:
        _check_manager(assigned_to, lead.branch_id)
    with transaction.atomic():
        task = FollowUpTask.objects.create(
            lead=lead, assigned_to=assigned_to, due_at=due_at, title=title.strip()
        )
        _log(lead, actor, LeadActivity.Kind.TASK, text=task.title)
        _refresh_follow_up(lead)
    return task


def complete_task(*, actor, task: FollowUpTask) -> FollowUpTask:
    require_perm(actor, "crm.leads.edit")
    ensure_branch_access(actor, task.lead.branch_id)
    with transaction.atomic():
        task = FollowUpTask.objects.select_for_update().get(pk=task.pk)
        if task.done_at is None:
            task.done_at = timezone.now()
            task.done_by = actor
            task.save(update_fields=["done_at", "done_by"])
            _refresh_follow_up(task.lead)
    return task


def reopen_task(*, actor, task: FollowUpTask) -> FollowUpTask:
    """Undo "done" (the toast's undo button): the task is open again."""
    require_perm(actor, "crm.leads.edit")
    ensure_branch_access(actor, task.lead.branch_id)
    with transaction.atomic():
        task = FollowUpTask.objects.select_for_update().get(pk=task.pk)
        if task.done_at is not None:
            task.done_at = None
            task.done_by = None
            task.save(update_fields=["done_at", "done_by"])
            _refresh_follow_up(task.lead)
    return task


# --- Trial lessons --------------------------------------------------------------------

BEFORE_TRIAL = {Kind.NEW, Kind.CONTACTED, Kind.CUSTOM}


def book_trial(*, actor, lead: Lead, group, scheduled_date: dt.date, note: str = "") -> TrialLesson:
    """Book a free trial lesson in a real lesson of a group of the lead's branch."""
    require_perm(actor, "crm.leads.edit")
    ensure_branch_access(actor, lead.branch_id)
    with transaction.atomic():
        lead = _lock(lead)
        if lead.is_converted or lead.is_lost:
            raise ValidationError(_("Reopen the lead before booking a trial lesson."))
        if scheduled_date < dates.today():
            raise ValidationError(_("The trial lesson date can't be in the past."))
        if group.branch_id != lead.branch_id:
            raise ValidationError(_("The group is in another branch."))
        lesson = (
            Lesson.objects.filter(group=group, date=scheduled_date)
            .exclude(status=Lesson.Status.CANCELLED)
            .order_by("start_time")
            .first()
        )
        if lesson is None:
            raise ValidationError(_("This group has no lesson on that date."))
        trial = TrialLesson.objects.create(
            lead=lead, group=group, lesson=lesson, scheduled_date=scheduled_date, note=note
        )
        old = lead.stage
        if old.kind in BEFORE_TRIAL:
            lead.stage = selectors.stage_of_kind(Kind.TRIAL_BOOKED)
            lead.save()
        _log(lead, actor, LeadActivity.Kind.TRIAL, text=note, from_stage=old, to_stage=lead.stage)
        events.publish(
            TrialLessonBooked(
                lead_id=lead.pk, trial_id=trial.pk, scheduled_date=scheduled_date.isoformat()
            )
        )
    return trial


def set_trial_status(*, actor, trial: TrialLesson, status: str) -> TrialLesson:
    require_perm(actor, "crm.leads.edit")
    ensure_branch_access(actor, trial.lead.branch_id)
    if status not in TrialLesson.Status.values:
        raise ValidationError(_("Unknown status."))
    with transaction.atomic():
        trial = TrialLesson.objects.select_for_update().get(pk=trial.pk)
        lead = _lock(trial.lead)
        if trial.status == status:
            return trial
        trial.status = status
        trial.save(update_fields=["status"])
        old = lead.stage
        if status == TrialLesson.Status.ATTENDED and old.kind in BEFORE_TRIAL | {Kind.TRIAL_BOOKED}:
            lead.stage = selectors.stage_of_kind(Kind.TRIAL_ATTENDED)
            lead.save()
        _log(lead, actor, LeadActivity.Kind.TRIAL, from_stage=old, to_stage=lead.stage)
    return trial


# --- Conversion ---------------------------------------------------------------------


def convert(*, actor, lead: Lead, student_data: dict, confirm_duplicate=False):
    """Create the student from the lead. The lead and its full history stay (SPEC 6.2)."""
    require_perm(actor, "crm.leads.convert")
    ensure_branch_access(actor, lead.branch_id)
    with transaction.atomic():
        lead = _lock(lead)
        if lead.is_converted:
            raise ValidationError(_("This lead is already a student."))
        phones = [student_data.get("phone"), student_data.get("parent_phone")]
        dups = selectors.find_duplicates(actor, phones, exclude_lead_id=lead.pk)
        if (dups.students or dups.other_branches) and not confirm_duplicate:
            raise DuplicateWarning(dups)
        student = student_services.create_student(
            actor=actor, branch=lead.branch, data=student_data, lead=lead
        )
        old = lead.stage
        lead.stage = selectors.stage_of_kind(Kind.WON)
        lead.student = student
        lead.converted_at = timezone.now()
        lead.refusal_reason = None
        lead.refusal_note = ""
        lead.save()
        _log(lead, actor, LeadActivity.Kind.CONVERTED, from_stage=old, to_stage=lead.stage)
        lead.tasks.filter(done_at__isnull=True).update(done_at=timezone.now(), done_by=actor)
        _refresh_follow_up(lead)
        audit.record(
            actor,
            "crm.lead.convert",
            lead,
            before={"stage": old.pk, "student": None},
            after={"stage": lead.stage_id, "student": student.pk},
        )
        events.publish(
            LeadConverted(lead_id=lead.pk, student_id=student.pk, branch_id=lead.branch_id)
        )
    return student
