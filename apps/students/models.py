"""Students module: students, groups, schedule, lessons, enrollments, attendance, imports.

docs/SPEC.md 5.5 and 6.3. Attendance is informational only in module 1 (no billing effect).
"""

from django.db import models
from django.db.models.functions import Concat
from django.utils.translation import gettext_lazy as _

from apps.settings.models import Branch, Course, Room


class ImportBatch(models.Model):
    """One uploaded Excel file. Every imported row points back here (SPEC 6.5)."""

    class Kind(models.TextChoices):
        GROUPS = "groups", _("Groups")
        STUDENTS = "students", _("Students")
        OPENING_BALANCES = "opening_balances", _("Opening balances")
        DISCOUNTS = "discounts", _("Discounts")

    class Status(models.TextChoices):
        VALIDATED = "validated", _("Checked, ready to import")
        COMMITTED = "committed", _("Imported")
        FAILED = "failed", _("Has errors")

    kind = models.CharField(_("Type"), max_length=20, choices=Kind.choices)
    file_name = models.CharField(_("File"), max_length=255)
    file = models.FileField(upload_to="imports/%Y/%m/")
    uploaded_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="+", verbose_name=_("Uploaded by")
    )
    status = models.CharField(_("Status"), max_length=10, choices=Status.choices)
    row_count = models.PositiveIntegerField(_("Rows"), default=0)
    # {"branch_id": .., "update_existing": .., "errors": [...], "summary": {...}}
    report = models.JSONField(default=dict)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "students_import_batch"
        ordering = ["-created_at"]
        verbose_name = _("Import")
        verbose_name_plural = _("Imports")

    def __str__(self):
        return self.file_name

    @property
    def branch_id(self):
        return self.report.get("branch_id")


class Student(models.Model):
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name="students", verbose_name=_("Branch")
    )
    first_name = models.CharField(_("First name"), max_length=100)
    last_name = models.CharField(_("Last name"), max_length=100)
    middle_name = models.CharField(_("Middle name"), max_length=100, blank=True)
    birth_date = models.DateField(_("Date of birth"), null=True, blank=True)
    phone = models.CharField(_("Phone"), max_length=13, blank=True, db_index=True)
    parent_name = models.CharField(_("Parent's name"), max_length=150, blank=True)
    parent_phone = models.CharField(_("Parent's phone"), max_length=13, blank=True, db_index=True)
    extra_phone = models.CharField(_("Extra phone"), max_length=13, blank=True, db_index=True)
    notes = models.TextField(_("Notes"), blank=True)
    # The lead this student was converted from. crm owns the conversion; this module never
    # reads it (crm sits above students in the module graph).
    lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Lead"),
    )
    import_batch = models.ForeignKey(
        ImportBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        db_table = "students_student"
        ordering = ["last_name", "first_name"]
        verbose_name = _("Student")
        verbose_name_plural = _("Students")
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(phone="") | ~models.Q(parent_phone=""),
                name="student_has_a_phone",
                violation_error_message=_("Enter the student's or the parent's phone."),
            )
        ]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)


FULL_NAME = Concat("last_name", models.Value(" "), "first_name")


class Group(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        ACTIVE = "active", _("Active")
        FINISHED = "finished", _("Finished")

    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, related_name="groups", verbose_name=_("Branch")
    )
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="groups", verbose_name=_("Course")
    )
    teacher = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="teaching_groups",
        verbose_name=_("Teacher"),
    )
    room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="groups",
        verbose_name=_("Room"),
    )
    name = models.CharField(_("Group name"), max_length=100)
    start_date = models.DateField(_("Start date"))
    end_date = models.DateField(_("End date"), null=True, blank=True)
    capacity = models.PositiveIntegerField(_("Capacity"), default=12)
    status = models.CharField(
        _("Status"), max_length=10, choices=Status.choices, default=Status.ACTIVE
    )
    # Billing reads this; students only stores it (billing sits above students).
    default_installment_template = models.ForeignKey(
        "billing.InstallmentTemplate",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Installment template"),
    )
    import_batch = models.ForeignKey(
        ImportBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "students_group"
        ordering = ["name"]
        verbose_name = _("Group")
        verbose_name_plural = _("Groups")
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="uniq_group_name_per_branch",
                violation_error_message=_("This branch already has a group with this name."),
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="group_end_after_start",
                violation_error_message=_("The end date must be after the start date."),
            ),
        ]

    def __str__(self):
        return self.name


class ScheduleSlot(models.Model):
    class Weekday(models.IntegerChoices):
        MON = 1, _("Monday")
        TUE = 2, _("Tuesday")
        WED = 3, _("Wednesday")
        THU = 4, _("Thursday")
        FRI = 5, _("Friday")
        SAT = 6, _("Saturday")
        SUN = 7, _("Sunday")

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="slots")
    weekday = models.PositiveSmallIntegerField(_("Day"), choices=Weekday.choices)
    start_time = models.TimeField(_("Starts"))
    end_time = models.TimeField(_("Ends"))
    room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Room"),
    )

    class Meta:
        db_table = "students_schedule_slot"
        ordering = ["weekday", "start_time"]
        verbose_name = _("Schedule slot")
        verbose_name_plural = _("Schedule")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="slot_end_after_start",
                violation_error_message=_("The lesson must end after it starts."),
            )
        ]

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start_time:%H:%M}"


class Lesson(models.Model):
    """Materialized from the schedule. Proration counts these rows (SPEC 6.4.2)."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", _("Scheduled")
        HELD = "held", _("Held")
        CANCELLED = "cancelled", _("Cancelled")

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="lessons")
    date = models.DateField(_("Date"), db_index=True)
    start_time = models.TimeField(_("Starts"))
    end_time = models.TimeField(_("Ends"))
    room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Room"),
    )
    status = models.CharField(
        _("Status"), max_length=10, choices=Status.choices, default=Status.SCHEDULED
    )
    cancel_reason = models.CharField(_("Cancellation reason"), max_length=255, blank=True)

    class Meta:
        db_table = "students_lesson"
        ordering = ["date", "start_time"]
        verbose_name = _("Lesson")
        verbose_name_plural = _("Lessons")
        constraints = [
            models.UniqueConstraint(
                fields=["group", "date", "start_time"], name="uniq_lesson_per_group_time"
            )
        ]

    def __str__(self):
        return f"{self.group} {self.date}"


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Studying")
        FROZEN = "frozen", _("Frozen")
        LEFT = "left", _("Left")
        MOVED = "moved", _("Moved to another group")
        COMPLETED = "completed", _("Completed")

    OPEN = (Status.ACTIVE, Status.FROZEN)

    student = models.ForeignKey(
        Student, on_delete=models.PROTECT, related_name="enrollments", verbose_name=_("Student")
    )
    group = models.ForeignKey(
        Group, on_delete=models.PROTECT, related_name="enrollments", verbose_name=_("Group")
    )
    start_date = models.DateField(_("Start date"))
    # First day the student no longer attends (exclusive).
    end_date = models.DateField(_("End date"), null=True, blank=True)
    status = models.CharField(
        _("Status"), max_length=10, choices=Status.choices, default=Status.ACTIVE
    )
    import_batch = models.ForeignKey(
        ImportBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "students_enrollment"
        ordering = ["-start_date", "-id"]
        verbose_name = _("Enrollment")
        verbose_name_plural = _("Enrollments")
        constraints = [
            models.UniqueConstraint(
                fields=["student", "group"],
                condition=models.Q(status__in=["active", "frozen"]),
                name="uniq_open_enrollment",
                violation_error_message=_("The student is already in this group."),
            )
        ]

    def __str__(self):
        return f"{self.student} → {self.group}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN


class LeaveReason(models.Model):
    """Why a student left a group (editable list in Sozlamalar, like lead refusal reasons)."""

    name = models.CharField(_("Name"), max_length=150, unique=True)
    sort_order = models.PositiveIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        db_table = "students_leave_reason"
        ordering = ["sort_order", "name"]
        verbose_name = _("Leave reason")
        verbose_name_plural = _("Leave reasons")

    def __str__(self):
        return self.name


class EnrollmentEvent(models.Model):
    class Kind(models.TextChoices):
        ENROLLED = "enrolled", _("Enrolled into the group")
        FROZEN = "frozen", _("Frozen")
        UNFROZEN = "unfrozen", _("Unfrozen")
        MOVED_OUT = "moved_out", _("Moved to another group")
        MOVED_IN = "moved_in", _("Moved from another group")
        LEFT = "left", _("Left the group")
        COMPLETED = "completed", _("Completed")

    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(_("Action"), max_length=12, choices=Kind.choices)
    effective_date = models.DateField(_("Date"))
    reason = models.TextField(_("Reason"), blank=True)
    leave_reason = models.ForeignKey(
        LeaveReason,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Leave reason"),
    )
    related_enrollment = models.ForeignKey(
        Enrollment, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "students_enrollment_event"
        ordering = ["-created_at", "-id"]
        verbose_name = _("Enrollment event")
        verbose_name_plural = _("Enrollment history")

    def __str__(self):
        return f"{self.enrollment_id}:{self.kind}"


class Freeze(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name="freezes")
    from_date = models.DateField(_("From"))
    to_date = models.DateField(_("To"), null=True, blank=True)
    reason = models.TextField(_("Reason"))

    class Meta:
        db_table = "students_freeze"
        ordering = ["-from_date"]
        verbose_name = _("Freeze")
        verbose_name_plural = _("Freezes")

    def __str__(self):
        return f"{self.enrollment_id}:{self.from_date}"


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", _("Came")
        ABSENT = "absent", _("Did not come")

    lesson = models.ForeignKey(Lesson, on_delete=models.PROTECT, related_name="attendance")
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name="+")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="attendance")
    status = models.CharField(_("Attendance"), max_length=10, choices=Status.choices)
    marked_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    marked_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "students_attendance"
        verbose_name = _("Attendance")
        verbose_name_plural = _("Attendance")
        constraints = [
            models.UniqueConstraint(fields=["lesson", "student"], name="uniq_attendance")
        ]

    def __str__(self):
        return f"{self.lesson_id}:{self.student_id}:{self.status}"
