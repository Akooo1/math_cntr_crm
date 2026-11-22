from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.forms import PhoneField, StyledForm, StyledModelForm
from apps.core.roles import Role

from .models import Branch, BranchReceiptInfo, CenterInfo, Course, Room

User = get_user_model()


class BranchForm(StyledModelForm):
    phone = PhoneField(label=_("Phone"), required=False)

    class Meta:
        model = Branch
        fields = ["name", "address", "phone", "receipt_prefix"]

    def clean_receipt_prefix(self):
        return self.cleaned_data["receipt_prefix"].upper()


class RoomForm(StyledModelForm):
    class Meta:
        model = Room
        fields = ["branch", "name", "capacity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True)


class CourseForm(StyledModelForm):
    class Meta:
        model = Course
        fields = ["name", "pricing_model", "duration_months", "description"]


class CenterInfoForm(StyledModelForm):
    phone = PhoneField(label=_("Phone"), required=False)

    class Meta:
        model = CenterInfo
        fields = ["center_name", "legal_name", "inn", "phone", "bank_details", "receipt_footer"]


class BranchReceiptInfoForm(StyledModelForm):
    phone = PhoneField(label=_("Phone"), required=False)

    class Meta:
        model = BranchReceiptInfo
        fields = ["legal_name", "inn", "address", "phone", "footer"]
        help_texts = {"legal_name": _("Leave empty to use the center's details.")}


class StaffUserForm(StyledForm):
    full_name = forms.CharField(label=_("Full name"), max_length=150)
    phone = PhoneField(label=_("Phone"), help_text=_("Used to log in."))
    role = forms.ChoiceField(label=_("Role"), choices=Role.choices)
    branches = forms.ModelMultipleChoiceField(
        label=_("Branches"),
        queryset=Branch.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=_("The director works in all branches automatically."),
    )
    password = forms.CharField(
        label=_("Temporary password"),
        strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text=_("The user must change it at first login."),
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        self.fields["branches"].queryset = Branch.objects.filter(is_active=True)
        if instance is not None:
            del self.fields["password"]
            self.initial.update(
                full_name=instance.full_name,
                phone=instance.phone,
                role=instance.role,
                branches=list(instance.branch_links.values_list("branch_id", flat=True)),
            )

    def clean_phone(self):
        value = self.cleaned_data["phone"]
        qs = User.objects.filter(phone=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(_("A user with this phone number already exists."))
        return value

    def clean(self):
        data = super().clean()
        if data.get("role") and data["role"] != Role.DIRECTOR and not data.get("branches"):
            self.add_error("branches", _("Choose at least one branch."))
        return data


class PasswordResetForm(StyledForm):
    password = forms.CharField(
        label=_("New temporary password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=_("The user must change it at next login."),
    )
