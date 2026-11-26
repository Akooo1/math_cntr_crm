"""Early-warning tasks (docs/SPEC.md §19)."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Task(models.Model):
    """Made by the checking job (`run_alerts`), closed by a person or automatically when the
    cause goes away (the student came, the debt was paid, the lead was contacted)."""

    class Kind(models.TextChoices):
        ABSENCE = "absence", _("Missed lessons")
        DEBT = "debt", _("Overdue debt")
        LEAD = "lead", _("Lead not contacted")

    class Closed(models.TextChoices):
        DONE = "done", _("Done")
        RESOLVED = "resolved", _("Resolved by itself")

    kind = models.CharField(_("Type"), max_length=10, choices=Kind.choices)
    branch = models.ForeignKey(
        "center_settings.Branch",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Branch"),
    )
    student = models.ForeignKey(
        "students.Student",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Student"),
    )
    group = models.ForeignKey(
        "students.Group",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Group"),
    )
    lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Lead"),
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Assignee"),
    )
    details = models.JSONField(_("Details"), default=dict)
    # One task per cause: "absence:<enrollment>:<first missed lesson>", "debt:<student>:..."
    key = models.CharField(max_length=80, unique=True)
    due_at = models.DateTimeField(_("Due"), null=True, blank=True)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    closed_at = models.DateTimeField(_("Closed at"), null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Closed by"),
    )
    closed_how = models.CharField(
        _("How closed"), max_length=10, choices=Closed.choices, blank=True
    )

    class Meta:
        db_table = "alerts_task"
        ordering = ["-created_at", "-id"]
        verbose_name = _("Warning")
        verbose_name_plural = _("Warnings")
        indexes = [models.Index(fields=["closed_at", "branch"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(closed_at__isnull=True, closed_how="")
                | models.Q(closed_at__isnull=False) & ~models.Q(closed_how=""),
                name="alerts_task_closed_consistent",
            )
        ]

    def __str__(self):
        return self.key
