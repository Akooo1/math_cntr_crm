"""Form building blocks: Uzbek formats for money, phone and dates; Tailwind styling."""

import datetime as dt

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from . import dates, money, phone

INPUT_CSS = "input"
CHECK_CSS = "check"


class DateInput(forms.TextInput):
    input_type = "text"

    def __init__(self, attrs=None):
        base = {"placeholder": _("DD.MM.YYYY"), "inputmode": "numeric", "data-mask": "date"}
        super().__init__({**base, **(attrs or {})})

    def format_value(self, value):
        if isinstance(value, dt.date):
            return dates.format_date(value)
        return value


class TimeInput(forms.TextInput):
    """24-hour HH:MM as text: native time pickers show AM/PM in English-locale browsers."""

    def __init__(self, attrs=None):
        base = {"placeholder": _("HH:MM"), "inputmode": "numeric", "data-mask": "time"}
        super().__init__({**base, **(attrs or {})})

    def format_value(self, value):
        if isinstance(value, dt.time):
            return value.strftime("%H:%M")
        return value


class UzTimeField(forms.TimeField):
    widget = TimeInput
    input_formats = ["%H:%M", "%H.%M"]
    default_error_messages = {"invalid": _("Enter the time as HH:MM, for example 15:30.")}


class MoneyInput(forms.TextInput):
    def __init__(self, attrs=None):
        base = {"inputmode": "numeric", "data-money": "1", "autocomplete": "off"}
        super().__init__({**base, **(attrs or {})})

    def format_value(self, value):
        if isinstance(value, int):
            return money.group_digits(value).replace(" ", " ")
        return value


class PhoneInput(forms.TextInput):
    input_type = "tel"

    def __init__(self, attrs=None):
        base = {"placeholder": "+998 90 123 45 67", "inputmode": "tel", "autocomplete": "tel"}
        super().__init__({**base, **(attrs or {})})

    def format_value(self, value):
        return phone.format_phone(value) if value else value


class UzDateField(forms.DateField):
    widget = DateInput
    input_formats = [dates.DATE_FMT]
    default_error_messages = {"invalid": _("Enter the date as DD.MM.YYYY.")}


class MoneyField(forms.Field):
    widget = MoneyInput
    default_error_messages = {
        "invalid": _("Enter a whole amount in so'm, for example 450 000."),
        "min_value": _("The amount must be at least %(limit)s."),
    }

    def __init__(self, *, min_value: int | None = 0, **kwargs):
        self.min_value = min_value
        super().__init__(**kwargs)

    def to_python(self, value):
        if value in self.empty_values:
            return None
        try:
            return money.parse_amount(value)
        except ValueError as exc:
            raise ValidationError(self.error_messages["invalid"], code="invalid") from exc

    def validate(self, value):
        super().validate(value)
        if value is not None and self.min_value is not None and value < self.min_value:
            raise ValidationError(
                self.error_messages["min_value"],
                code="min_value",
                params={"limit": money.format_som(self.min_value)},
            )


class PhoneField(forms.CharField):
    widget = PhoneInput
    default_error_messages = {
        "invalid": _("Enter a phone number in the format +998 90 123 45 67."),
    }

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return ""
        try:
            return phone.normalize(value)
        except phone.InvalidPhone as exc:
            raise ValidationError(self.error_messages["invalid"], code="invalid") from exc


class StyledFormMixin:
    """Applies the shared Tailwind classes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()

    def style_fields(self):
        for f in self.fields.values():
            w = f.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs.setdefault("class", CHECK_CSS)
            elif isinstance(w, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                # Django puts widget attrs on the list's wrapper <div> too, so a size class
                # here squeezed the whole list into 20 px. The inputs are styled by
                # `.checkbox-list input` in assets/app.css instead.
                pass
            else:
                w.attrs.setdefault("class", INPUT_CSS)
            if isinstance(w, forms.Textarea):
                w.attrs["rows"] = 3
            if isinstance(f, forms.ModelChoiceField) and f.empty_label == "---------":
                f.empty_label = _("Choose")


class StyledForm(StyledFormMixin, forms.Form):
    pass


class StyledModelForm(StyledFormMixin, forms.ModelForm):
    pass
