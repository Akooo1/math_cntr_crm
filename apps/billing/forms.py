import re
from fractions import Fraction

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core import money
from apps.core.forms import MoneyField, StyledForm, StyledModelForm, UzDateField
from apps.settings.models import Branch, Course
from apps.students.models import Group

from .domain.rounding import BP
from .models import DiscountType, InstallmentTemplate, PaymentMethod


class PriceForm(StyledForm):
    course = forms.ModelChoiceField(label=_("Course"), queryset=Course.objects.none())
    branch = forms.ModelChoiceField(
        label=_("Branch"),
        queryset=Branch.objects.none(),
        required=False,
        empty_label=_("All branches"),
    )
    group = forms.ModelChoiceField(
        label=_("Group"),
        queryset=Group.objects.none(),
        required=False,
        empty_label=_("All groups"),
        help_text=_("Only for a special price in one group."),
    )
    amount = MoneyField(label=_("Amount"), min_value=1)
    effective_from = UzDateField(label=_("Effective from"))
    note = forms.CharField(label=_("Note"), max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.filter(is_active=True)
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True)
        self.fields["group"].queryset = (
            Group.objects.exclude(status=Group.Status.FINISHED)
            .select_related("course", "branch")
            .order_by("name")
        )
        self.fields["group"].label_from_instance = lambda g: f"{g.name} ({g.branch.name})"


def parse_percent_bp(raw: str) -> int:
    """'10' -> 1000, '12,5' -> 1250, '7.25' -> 725 (basis points)."""
    text = raw.strip().replace(",", ".").rstrip("%").strip()
    if not re.fullmatch(r"\d{1,3}(\.\d{1,2})?", text):
        raise ValueError(raw)
    return int(Fraction(text) * 100)


def format_percent_bp(bp: int) -> str:
    whole, rest = divmod(bp, 100)
    return f"{whole}" if rest == 0 else f"{whole},{rest:02d}".rstrip("0")


class DiscountTypeForm(StyledModelForm):
    value_text = forms.CharField(
        label=_("Value"),
        help_text=_("For a percent enter e.g. 10 or 12,5. For a fixed amount enter so'm."),
    )

    class Meta:
        model = DiscountType
        fields = ["name", "kind", "applies_to", "allow_custom_value"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = self.instance
        if inst.pk:
            self.initial["value_text"] = (
                format_percent_bp(inst.value)
                if inst.kind == DiscountType.Kind.PERCENT
                else money.group_digits(inst.value).replace(" ", " ")
            )

    def clean(self):
        data = super().clean()
        raw = data.get("value_text")
        kind = data.get("kind")
        if raw and kind:
            try:
                value = parse_percent_bp(raw) if kind == "percent" else money.parse_amount(raw)
            except ValueError:
                self.add_error("value_text", _("Enter a valid number."))
                return data
            if value <= 0 or (kind == "percent" and value > BP):
                self.add_error("value_text", _("A percent must be above 0 and at most 100."))
            else:
                self.instance.value = value
        return data


class PaymentMethodForm(StyledModelForm):
    class Meta:
        model = PaymentMethod
        fields = ["name", "included_in_cash_close", "sort_order"]


class InstallmentTemplateForm(StyledModelForm):
    shares = forms.CharField(
        label=_("Shares of each part (%)"),
        required=False,
        help_text=_("Only for custom shares: e.g. 40, 30, 30. The total must be 100."),
    )

    class Meta:
        model = InstallmentTemplate
        fields = [
            "name",
            "course",
            "parts_count",
            "split_mode",
            "first_due",
            "interval_months",
            "due_day_of_month",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.filter(
            is_active=True, pricing_model=Course.PricingModel.INSTALLMENT
        )
        self.fields["course"].empty_label = _("All installment courses")
        if self.instance.pk and self.instance.split_mode == "custom":
            self.initial["shares"] = ", ".join(
                format_percent_bp(bp) for bp in self.instance.shares_bp()
            )
        self.shares_bp: list[int] = []

    def clean(self):
        data = super().clean()
        if data.get("first_due") == "fixed_day" and not data.get("due_day_of_month"):
            self.add_error("due_day_of_month", _("Choose the day of the month."))
        if data.get("split_mode") == "custom":
            raw = data.get("shares") or ""
            try:
                shares = [parse_percent_bp(p) for p in raw.split(",") if p.strip()]
            except ValueError:
                self.add_error("shares", _("Enter numbers separated by commas."))
                return data
            if len(shares) != data.get("parts_count"):
                self.add_error("shares", _("The number of shares must equal the number of parts."))
            elif sum(shares) != BP or any(s <= 0 for s in shares):
                self.add_error("shares", _("The shares must be above 0 and add up to 100."))
            else:
                self.shares_bp = shares
        return data


# =========================================================================================
# Ledger forms
# =========================================================================================

_UzDate = UzDateField


class PaymentForm(StyledForm):
    amount = MoneyField(label=_("Amount"), min_value=1)
    method = forms.ModelChoiceField(
        label=_("Payment method"), queryset=PaymentMethod.objects.none(), empty_label=None
    )
    paid_on = _UzDate(label=_("Date"))
    comment = forms.CharField(label=_("Comment"), max_length=255, required=False)
    branch = forms.ModelChoiceField(
        label=_("Branch"), queryset=Branch.objects.none(), required=False
    )

    def __init__(self, *args, methods, branches=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].queryset = methods
        if branches is not None and branches.count() > 1:
            self.fields["branch"].queryset = branches
            self.fields["branch"].empty_label = _("Student's branch")
        else:
            del self.fields["branch"]


class ReasonForm(StyledForm):
    reason = forms.CharField(label=_("Reason"), widget=forms.Textarea)


class RefundForm(StyledForm):
    amount = MoneyField(label=_("Amount"), min_value=1)
    method = forms.ModelChoiceField(
        label=_("Payment method"), queryset=PaymentMethod.objects.none(), empty_label=None
    )
    reason = forms.CharField(label=_("Reason"), widget=forms.Textarea)

    def __init__(self, *args, methods, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].queryset = methods


class DiscountAssignForm(StyledForm):
    enrollment = forms.ModelChoiceField(label=_("Group"), queryset=None, empty_label=None)
    discount_type = forms.ModelChoiceField(
        label=_("Discount type"), queryset=DiscountType.objects.none()
    )
    value_text = forms.CharField(
        label=_("Custom value"),
        required=False,
        help_text=_(
            "Only the director, and only for discounts that allow it. Empty = the type's value."
        ),
    )
    valid_from = _UzDate(label=_("From"))
    valid_to = _UzDate(label=_("To"), required=False)
    reason = forms.CharField(label=_("Reason"), widget=forms.Textarea, required=False)

    def __init__(self, *args, enrollments, can_custom, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["enrollment"].queryset = enrollments
        self.fields["enrollment"].label_from_instance = lambda e: e.group.name
        self.fields["discount_type"].queryset = DiscountType.objects.filter(is_active=True)
        if not can_custom:
            del self.fields["value_text"]

    def custom_value(self):
        raw = (self.cleaned_data.get("value_text") or "").strip()
        dtype = self.cleaned_data.get("discount_type")
        if not raw or dtype is None:
            return None
        try:
            return parse_percent_bp(raw) if dtype.kind == "percent" else money.parse_amount(raw)
        except ValueError as exc:
            raise forms.ValidationError(_("Enter a valid number.")) from exc


class EndDateForm(StyledForm):
    valid_to = _UzDate(label=_("Last day of the discount"))


class CorrectionForm(StyledForm):
    new_net = MoneyField(label=_("New amount"), min_value=0, help_text=_("0 cancels the charge."))
    reason = forms.CharField(label=_("Reason"), widget=forms.Textarea)


class ManualChargeForm(StyledForm):
    description = forms.CharField(label=_("What is it for"), max_length=255)
    amount = MoneyField(label=_("Amount"), min_value=1)
    due_date = _UzDate(label=_("Due date"))


class CashCloseForm(StyledForm):
    note = forms.CharField(label=_("Note"), max_length=255, required=False)
