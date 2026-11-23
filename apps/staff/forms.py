import re

from django import forms
from django.utils.dates import WEEKDAYS
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledForm, UzDateField, UzTimeField

from . import selectors

COORDS = re.compile(r"^\s*(-?\d{1,2}(?:[.,]\d+)?)\s*[,; ]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*$")


def parse_coordinates(raw: str) -> tuple[float, float]:
    """ "41.311081, 69.240562" (as copied from Google or Yandex Maps) -> floats."""
    m = COORDS.match(raw or "")
    if not m:
        raise ValueError(raw)
    lat, lon = (float(x.replace(",", ".")) for x in m.groups())
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(raw)
    return lat, lon


class LocationForm(StyledForm):
    coordinates = forms.CharField(
        label=_("Coordinates"),
        help_text=_(
            'Stand in the branch and press "Use my location", or paste the coordinates '
            "from Google or Yandex Maps, e.g. 41.311081, 69.240562."
        ),
        max_length=60,
        widget=forms.TextInput(attrs={"data-geo-coords": "", "inputmode": "decimal"}),
    )
    radius_m = forms.IntegerField(
        label=_("Radius (m)"),
        min_value=30,
        max_value=2000,
        initial=200,
        help_text=_('How far from this point an employee may press "Keldim".'),
    )

    def clean_coordinates(self):
        try:
            return parse_coordinates(self.cleaned_data["coordinates"])
        except ValueError:
            raise forms.ValidationError(
                _("Enter the coordinates as two numbers, e.g. 41.311081, 69.240562.")
            ) from None


class ScheduleForm(StyledForm):
    start_time = UzTimeField(
        label=_("Start time"),
        required=False,
        help_text=_("Leave empty: arrival is recorded but never counted as late."),
    )
    workdays = forms.TypedMultipleChoiceField(
        label=_("Workdays"),
        choices=[(d, WEEKDAYS[d - 1]) for d in range(1, 8)],
        coerce=int,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        initial=[1, 2, 3, 4, 5, 6],
    )


class ManualCheckInForm(StyledForm):
    user = forms.ModelChoiceField(queryset=None, label=_("Employee"))
    branch = forms.ModelChoiceField(queryset=None, label=_("Branch"))
    day = UzDateField(label=_("Date"))
    time = UzTimeField(label=_("Arrived at"))
    reason = forms.CharField(label=_("Reason"), max_length=300)

    def __init__(self, *args, viewer=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.settings.models import Branch

        self.fields["user"].queryset = selectors.staff(viewer)
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True).order_by("name")
        for name in ("user", "branch"):
            self.fields[name].empty_label = _("Choose")
