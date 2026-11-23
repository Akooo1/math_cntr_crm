from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core import dates
from apps.core.permissions import perm_required

from . import selectors, services
from .forms import ManualCheckInForm


def _float(raw):
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None


@perm_required("staff.checkin")
@require_POST
def check_in(request):
    lat, lon, acc = (_float(request.POST.get(k)) for k in ("lat", "lng", "accuracy"))
    if lat is None or lon is None:
        messages.error(request, _("The phone didn't share its location. Allow it and try again."))
        return redirect("core:home")
    try:
        checkin = services.check_in(
            actor=request.user,
            latitude=lat,
            longitude=lon,
            accuracy_m=acc,
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        if checkin.late_minutes:
            messages.warning(
                request,
                _("Arrival recorded. You are %(m)s minutes late.") % {"m": checkin.late_minutes},
            )
        else:
            messages.success(request, _("Arrival recorded. Have a good day!"))
    return redirect("core:home")


def _day(request):
    raw = request.GET.get("sana")
    try:
        return dates.parse_date(raw) if raw else dates.today()
    except ValueError:
        return dates.today()


@perm_required("staff.attendance.view")
def board(request):
    day = _day(request)
    data = selectors.board(request.user, day, request.branch_filter)
    form = ManualCheckInForm(
        viewer=request.user,
        initial={"day": day, "time": timezone.localtime(dates.now()).strftime("%H:%M")},
    )
    return render(request, "staff/board.html", {**data, "form": form})


@perm_required("staff.attendance.view")
@require_POST
def manual(request):
    form = ManualCheckInForm(request.POST, viewer=request.user)
    if form.is_valid():
        d = form.cleaned_data
        try:
            services.manual_check_in(
                actor=request.user,
                user=d["user"],
                branch=d["branch"],
                day=d["day"],
                time=d["time"],
                reason=d["reason"],
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, _("Arrival recorded."))
        day = d["day"]
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        day = dates.today()
    return redirect(f"{reverse('staff:board')}?sana={dates.format_date(day)}")
