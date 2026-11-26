"""Sozlamalar: Filial joylashuvi, Ish vaqti (docs/SPEC.md §14.2)."""

from django.contrib.auth import get_user_model
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from apps.core.settings_panel import SettingsSection
from apps.settings.models import Branch

from . import selectors, services
from .forms import LocationForm, ScheduleForm
from .models import BranchLocation, Schedule

GROUP = _("Staff")


def _locations_view(request, section):
    return render(
        request,
        "staff/locations.html",
        {"section": section, "rows": selectors.locations(request.branch_filter)},
    )


class LocationSection(SettingsSection):
    slug = "filial-joylashuvi"
    title = _("Branch location")
    description = _('Where each branch is, for the morning "Keldim" check.')
    icon = "map-pin"
    order = 75
    group = GROUP
    model = Branch
    custom_view = staticmethod(_locations_view)
    form_template = "staff/location_form.html"
    allow_create = False
    allow_toggle_active = False

    def get_queryset(self, request):
        return Branch.objects.filter(is_active=True)

    def get_form(self, request, instance=None, data=None):
        initial = {"radius_m": 200}
        loc = BranchLocation.objects.filter(branch=instance).first() if instance else None
        if loc:
            initial = {"coordinates": f"{loc.latitude}, {loc.longitude}", "radius_m": loc.radius_m}
        form = LocationForm(data=data, initial=initial)
        form.instance = instance
        return form

    def save(self, request, form):
        lat, lon = form.cleaned_data["coordinates"]
        return services.save_location(
            actor=request.user,
            branch=form.instance,
            latitude=lat,
            longitude=lon,
            radius_m=form.cleaned_data["radius_m"],
        )


def _schedules_view(request, section):
    from django.utils.dates import WEEKDAYS_ABBR

    from apps.core.system_settings import get_setting

    rows = selectors.schedules(request.branch_filter)
    for r in rows:
        if r["schedule"]:
            r["days"] = ", ".join(str(WEEKDAYS_ABBR[d - 1]) for d in r["schedule"].workdays)
    return render(
        request,
        "staff/schedules.html",
        {"section": section, "rows": rows, "grace": get_setting("staff.grace_minutes")},
    )


class ScheduleSection(SettingsSection):
    slug = "ish-vaqti"
    title = _("Work hours")
    description = _("Each employee's start time and workdays.")
    icon = "clock"
    order = 76
    group = GROUP
    model = get_user_model()
    custom_view = staticmethod(_schedules_view)
    allow_create = False
    allow_toggle_active = False

    def get_queryset(self, request):
        return selectors.staff()

    def get_form(self, request, instance=None, data=None):
        schedule = Schedule.objects.filter(user=instance).first() if instance else None
        initial = (
            {"start_time": schedule.start_time, "workdays": schedule.workdays}
            if schedule
            else {"workdays": [1, 2, 3, 4, 5, 6]}
        )
        form = ScheduleForm(data=data, initial=initial)
        form.instance = instance
        return form

    def save(self, request, form):
        return services.save_schedule(
            actor=request.user,
            user=form.instance,
            start_time=form.cleaned_data["start_time"],
            workdays=form.cleaned_data["workdays"],
        )
