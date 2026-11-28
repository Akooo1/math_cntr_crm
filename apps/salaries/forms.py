from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.datemath import add_months
from apps.core.forms import MoneyField, StyledForm, UzDateField

from . import selectors
from .formatting import parse_percent
from .models import Adjustment


def month_choices() -> list[tuple[str, str]]:
    """Open months from the first open one, 12 ahead."""
    from django.utils.dates import MONTHS

    m = selectors.open_month()
    out = []
    for _i in range(13):
        out.append((f"{m:%m.%Y}", f"{MONTHS[m.month]} {m.year}"))
        m = add_months(m, 1)
    return out


class RateForm(StyledForm):
    teacher = forms.ModelChoiceField(queryset=None, label=_("Teacher"))
    rate = forms.CharField(
        label=_("Rate (%)"),
        help_text=_("Share of the money students paid, e.g. 50 or 65."),
        max_length=6,
    )
    effective_from = forms.ChoiceField(label=_("From month"))
    reason = forms.CharField(label=_("Reason"), required=False, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["teacher"].queryset = selectors.teachers().filter(is_active=True)
        self.fields["teacher"].empty_label = _("Choose")
        self.fields["effective_from"].choices = month_choices()

    def clean_rate(self):
        try:
            bp = parse_percent(self.cleaned_data["rate"])
        except ValueError:
            raise forms.ValidationError(_("Enter a percent, for example 50 or 62,5.")) from None
        if bp > 10_000:
            raise forms.ValidationError(_("A percent must be between 0 and 100."))
        return bp

    def clean_effective_from(self):
        return selectors.parse_month(self.cleaned_data["effective_from"])


class StaffPayForm(StyledForm):
    user = forms.ModelChoiceField(queryset=None, label=_("Employee"))
    amount = MoneyField(label=_("Monthly salary"), help_text=_("0 stops the fixed salary."))
    effective_from = forms.ChoiceField(label=_("From month"))
    reason = forms.CharField(label=_("Reason"), required=False, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = selectors.salaried().filter(is_active=True)
        self.fields["user"].empty_label = _("Choose")
        self.fields["effective_from"].choices = month_choices()

    def clean_effective_from(self):
        return selectors.parse_month(self.cleaned_data["effective_from"])


class AdjustmentForm(StyledForm):
    kind = forms.ChoiceField(
        label=_("Type"),
        choices=[
            (Adjustment.Kind.BONUS, _("Bonus")),
            (Adjustment.Kind.DEDUCTION, _("Deduction")),
        ],
        widget=forms.RadioSelect,
        initial=Adjustment.Kind.BONUS,
    )
    amount = MoneyField(label=_("Amount"), min_value=1)
    reason = forms.CharField(label=_("Reason"), max_length=500)


def _kassa_fields(form):
    """Branch + cash desk method: salary money comes out of a branch's Kassa (SPEC §24)."""
    from apps.billing import selectors as billing_selectors
    from apps.settings.models import Branch

    form.fields["branch"].queryset = Branch.objects.filter(is_active=True).order_by("name")
    form.fields["method"].queryset = billing_selectors.cash_methods_for_entry()


class PayoutForm(StyledForm):
    paid_on = UzDateField(label=_("Date"))
    branch = forms.ModelChoiceField(label=_("From the Kassa of"), queryset=None)
    method = forms.ModelChoiceField(label=_("Payment method"), queryset=None, empty_label=None)
    note = forms.CharField(label=_("Note"), required=False, max_length=500)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _kassa_fields(self)


class AdvanceForm(StyledForm):
    amount = MoneyField(label=_("Amount"), min_value=1)
    given_on = UzDateField(label=_("Date"))
    branch = forms.ModelChoiceField(label=_("From the Kassa of"), queryset=None)
    method = forms.ModelChoiceField(label=_("Payment method"), queryset=None, empty_label=None)
    note = forms.CharField(label=_("Note"), required=False, max_length=500)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _kassa_fields(self)


class ReasonForm(StyledForm):
    reason = forms.CharField(label=_("Reason"), max_length=500)
