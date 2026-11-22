"""Roles are fixed in code (docs/SPEC.md section 4.5). Labels are translated."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    DIRECTOR = "director", _("Director")
    BRANCH_ADMIN = "branch_admin", _("Branch administrator")
    SALES_MANAGER = "sales_manager", _("Sales manager")
    TEACHER = "teacher", _("Teacher")


ALL_ROLES = frozenset(Role.values)
