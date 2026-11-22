"""Students module. Phase 2 creates only the student table (needed by lead conversion).

Groups, schedule, lessons, enrollments, attendance and the Excel import follow in phase 3
(docs/SPEC.md 5.5).
"""

from django.db import models
from django.db.models.functions import Concat
from django.utils.translation import gettext_lazy as _

from apps.settings.models import Branch


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
