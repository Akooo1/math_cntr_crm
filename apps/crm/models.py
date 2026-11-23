from django.db import models
from django.utils.translation import gettext_lazy as _

# Full Tailwind class strings (kept literal so the CSS build picks them up).
STAGE_COLORS = {
    "slate": "bg-slate-100 text-slate-800",
    "sky": "bg-sky-100 text-sky-800",
    "amber": "bg-amber-100 text-amber-800",
    "violet": "bg-violet-100 text-violet-800",
    "emerald": "bg-emerald-100 text-emerald-800",
    "rose": "bg-rose-100 text-rose-800",
}


class LeadSource(models.Model):
    name = models.CharField(_("Name"), max_length=100, unique=True)
    sort_order = models.PositiveIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        db_table = "crm_lead_source"
        ordering = ["sort_order", "name"]
        verbose_name = _("Lead source")
        verbose_name_plural = _("Lead sources")

    def __str__(self):
        return self.name


class LeadStage(models.Model):
    class Kind(models.TextChoices):
        NEW = "new", _("New")
        CONTACTED = "contacted", _("Contacted")
        TRIAL_BOOKED = "trial_booked", _("Booked for a trial lesson")
        TRIAL_ATTENDED = "trial_attended", _("Attended the trial lesson")
        WON = "won", _("Enrolled")
        LOST = "lost", _("Refused")
        CUSTOM = "custom", _("Extra stage")

    class Color(models.TextChoices):
        SLATE = "slate", _("Grey")
        SKY = "sky", _("Blue")
        AMBER = "amber", _("Yellow")
        VIOLET = "violet", _("Purple")
        EMERALD = "emerald", _("Green")
        ROSE = "rose", _("Red")

    name = models.CharField(_("Name"), max_length=100)
    kind = models.CharField(_("Stage type"), max_length=20, choices=Kind.choices)
    color = models.CharField(_("Color"), max_length=20, choices=Color.choices, default="slate")
    sort_order = models.PositiveIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        db_table = "crm_lead_stage"
        ordering = ["sort_order", "id"]
        verbose_name = _("Lead stage")
        verbose_name_plural = _("Lead stages")
        constraints = [
            models.UniqueConstraint(
                fields=["kind"],
                condition=~models.Q(kind="custom"),
                name="uniq_system_lead_stage_kind",
                violation_error_message=_("This stage type already exists."),
            )
        ]

    def __str__(self):
        return self.name

    @property
    def is_system(self) -> bool:
        return self.kind != self.Kind.CUSTOM

    @property
    def badge_css(self) -> str:
        return STAGE_COLORS.get(self.color, STAGE_COLORS["slate"])


class RefusalReason(models.Model):
    name = models.CharField(_("Name"), max_length=150, unique=True)
    sort_order = models.PositiveIntegerField(_("Order"), default=100)
    is_active = models.BooleanField(_("Active"), default=True)

    class Meta:
        db_table = "crm_refusal_reason"
        ordering = ["sort_order", "name"]
        verbose_name = _("Refusal reason")
        verbose_name_plural = _("Refusal reasons")

    def __str__(self):
        return self.name


class Lead(models.Model):
    branch = models.ForeignKey(
        "center_settings.Branch",
        on_delete=models.PROTECT,
        related_name="leads",
        verbose_name=_("Branch"),
    )
    full_name = models.CharField(_("Name"), max_length=150)
    phone = models.CharField(_("Phone"), max_length=13)
    # Digits only ("998901234567"): lets staff search by any part of the number.
    phone_normalized = models.CharField(max_length=12, db_index=True, editable=False)
    extra_phone = models.CharField(_("Extra phone"), max_length=13, blank=True, db_index=True)
    source = models.ForeignKey(
        LeadSource, on_delete=models.PROTECT, related_name="leads", verbose_name=_("Source")
    )
    course = models.ForeignKey(
        "center_settings.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name=_("Course of interest"),
    )
    manager = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="managed_leads",
        verbose_name=_("Manager"),
    )
    stage = models.ForeignKey(
        LeadStage, on_delete=models.PROTECT, related_name="leads", verbose_name=_("Stage")
    )
    refusal_reason = models.ForeignKey(
        RefusalReason,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name=_("Refusal reason"),
    )
    refusal_note = models.TextField(_("Refusal note"), blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    next_follow_up_at = models.DateTimeField(_("Next follow-up"), null=True, blank=True)
    student = models.ForeignKey(
        "students.Student",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Student"),
    )
    converted_at = models.DateTimeField(_("Converted at"), null=True, blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="+", verbose_name=_("Created by")
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        db_table = "crm_lead"
        ordering = ["-created_at"]
        verbose_name = _("Lead")
        verbose_name_plural = _("Leads")
        constraints = [
            models.UniqueConstraint(
                fields=["student"],
                condition=models.Q(student__isnull=False),
                name="uniq_lead_per_student",
            )
        ]

    def __str__(self):
        return self.full_name

    @property
    def is_converted(self) -> bool:
        return self.student_id is not None

    @property
    def is_lost(self) -> bool:
        return self.stage.kind == LeadStage.Kind.LOST


class LeadActivity(models.Model):
    """Lead history. Kept forever, also after conversion (docs/SPEC.md 5.4)."""

    class Kind(models.TextChoices):
        NOTE = "note", _("Note")
        CALL = "call", _("Call")
        STAGE_CHANGE = "stage_change", _("Stage change")
        TRIAL = "trial", _("Trial lesson")
        TASK = "task", _("Task")
        CONVERTED = "converted", _("Converted to a student")
        EDIT = "edit", _("Edited")
        CREATED = "created", _("Lead created")

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities")
    kind = models.CharField(_("Type"), max_length=20, choices=Kind.choices)
    text = models.TextField(_("Text"), blank=True)
    from_stage = models.ForeignKey(
        LeadStage, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    to_stage = models.ForeignKey(
        LeadStage, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "crm_lead_activity"
        ordering = ["-created_at", "-id"]
        verbose_name = _("Lead activity")
        verbose_name_plural = _("Lead activities")

    def __str__(self):
        return f"{self.lead_id}:{self.kind}"


class FollowUpTask(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="tasks")
    assigned_to = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="crm_tasks",
        verbose_name=_("Assigned to"),
    )
    due_at = models.DateTimeField(_("Due"), db_index=True)
    title = models.CharField(_("Task"), max_length=200)
    done_at = models.DateTimeField(_("Done at"), null=True, blank=True)
    done_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "crm_follow_up_task"
        ordering = ["due_at", "id"]
        verbose_name = _("Follow-up task")
        verbose_name_plural = _("Follow-up tasks")

    def __str__(self):
        return self.title

    @property
    def is_open(self) -> bool:
        return self.done_at is None


class TrialLesson(models.Model):
    """Free trial lesson (no charge) in a group lesson.

    `group` is nullable only for trials booked before groups existed (phase 2 data).
    """

    class Status(models.TextChoices):
        BOOKED = "booked", _("Booked")
        ATTENDED = "attended", _("Attended")
        NO_SHOW = "no_show", _("Did not come")
        CANCELLED = "cancelled", _("Cancelled")

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="trials")
    group = models.ForeignKey(
        "students.Group",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Group"),
    )
    lesson = models.ForeignKey(
        "students.Lesson",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Lesson"),
    )
    scheduled_date = models.DateField(_("Date"), db_index=True)
    status = models.CharField(
        _("Status"), max_length=10, choices=Status.choices, default=Status.BOOKED
    )
    note = models.TextField(_("Note"), blank=True)

    class Meta:
        db_table = "crm_trial_lesson"
        ordering = ["scheduled_date", "id"]
        verbose_name = _("Trial lesson")
        verbose_name_plural = _("Trial lessons")

    def __str__(self):
        return f"{self.lead_id}:{self.scheduled_date}"
