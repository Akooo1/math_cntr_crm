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
