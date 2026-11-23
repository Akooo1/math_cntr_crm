"""Sozlamalar → O'qituvchi stavkalari. Rates are add-only, like prices."""

from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from apps.core import dates
from apps.core.settings_panel import SettingsSection

from . import selectors, services
from .forms import RateForm
from .models import Rate


def _rates_view(request, section):
    return render(
        request,
        "salaries/rates.html",
        {"section": section, "rows": selectors.current_rates(), "today": dates.today()},
    )


class RateSection(SettingsSection):
    slug = "stavkalar"
    title = _("Teacher rates")
    description = _("Each teacher's share of the money students paid, with history.")
    icon = "wallet"
    order = 70
    group = _("Salaries")
    model = Rate
    custom_view = staticmethod(_rates_view)
    allow_edit = False
    allow_toggle_active = False

    def get_form(self, request, instance=None, data=None):
        initial = {}
        if request.GET.get("oqituvchi"):
            initial["teacher"] = request.GET["oqituvchi"]
        return RateForm(data=data, initial=initial)

    def save(self, request, form):
        d = form.cleaned_data
        return services.add_rate(
            actor=request.user,
            teacher=d["teacher"],
            rate_bp=d["rate"],
            effective_from=d["effective_from"],
            reason=d["reason"],
        )
