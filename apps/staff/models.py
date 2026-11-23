"""Staff arrival check-in (docs/SPEC.md §14.1)."""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class BranchLocation(models.Model):
    branch = models.OneToOneField(
        "center_settings.Branch",
        on_delete=models.PROTECT,
        related_name="location",
        verbose_name=_("Branch"),
    )
    latitude = models.FloatField(_("Latitude"))
    longitude = models.FloatField(_("Longitude"))
    radius_m = models.PositiveIntegerField(_("Radius (m)"), default=200)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staff_branch_location"
        verbose_name = _("Branch location")
        constraints = [
            models.CheckConstraint(
                condition=Q(radius_m__gte=30, radius_m__lte=2000), name="staff_radius_range"
            ),
            models.CheckConstraint(
                condition=Q(latitude__gte=-90, latitude__lte=90)
                & Q(longitude__gte=-180, longitude__lte=180),
                name="staff_location_valid",
            ),
        ]

    def __str__(self):
        return f"{self.branch_id}: {self.latitude}, {self.longitude}"


class Schedule(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="work_schedule",
        verbose_name=_("Employee"),
    )
    start_time = models.TimeField(_("Start time"))
    workdays = ArrayField(models.PositiveSmallIntegerField(), verbose_name=_("Workdays"))
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staff_schedule"
        verbose_name = _("Work schedule")

    def __str__(self):
        return f"{self.user_id}: {self.start_time} {self.workdays}"


class CheckIn(models.Model):
    class Source(models.TextChoices):
        GPS = "gps", _("Phone (GPS)")
        MANUAL = "manual", _("Entered by the Direktor")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="checkins",
        verbose_name=_("Employee"),
    )
    branch = models.ForeignKey(
        "center_settings.Branch",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Branch"),
    )
    date = models.DateField(_("Date"))
    checked_in_at = models.DateTimeField(_("Arrived at"))
    source = models.CharField(_("Source"), max_length=10, choices=Source.choices)
    latitude = models.FloatField(_("Latitude"), null=True, blank=True)
    longitude = models.FloatField(_("Longitude"), null=True, blank=True)
    accuracy_m = models.PositiveIntegerField(_("GPS accuracy (m)"), null=True, blank=True)
    distance_m = models.PositiveIntegerField(_("Distance (m)"), null=True, blank=True)
    expected_start = models.TimeField(_("Start time"), null=True, blank=True)
    late_minutes = models.PositiveIntegerField(_("Minutes late"), default=0)
    reason = models.TextField(_("Reason"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Created by"),
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "staff_checkin"
        verbose_name = _("Arrival")
        ordering = ["-date", "checked_in_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="staff_checkin_once_a_day"),
            models.CheckConstraint(
                condition=Q(source="manual") | Q(distance_m__isnull=False),
                name="staff_checkin_gps_has_distance",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} {self.date} {self.checked_in_at:%H:%M}"
