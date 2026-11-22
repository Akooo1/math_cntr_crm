from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.forms import PhoneField, StyledForm


class LoginForm(StyledForm):
    phone = PhoneField(label=_("Phone"))
    password = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class PasswordChangeForm(StyledForm):
    old_password = forms.CharField(
        label=_("Current password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    new_password1 = forms.CharField(
        label=_("New password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=_("At least 8 characters, not only digits."),
    )
    new_password2 = forms.CharField(
        label=_("Repeat the new password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        value = self.cleaned_data["old_password"]
        if not self.user.check_password(value):
            raise ValidationError(_("The current password is wrong."))
        return value

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("new_password1"), data.get("new_password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("new_password2", _("The passwords don't match."))
            else:
                try:
                    validate_password(p1, self.user)
                except ValidationError as exc:
                    self.add_error("new_password1", exc)
                if data.get("old_password") and p1 == data["old_password"]:
                    self.add_error(
                        "new_password1", _("The new password must differ from the current one.")
                    )
        return data
