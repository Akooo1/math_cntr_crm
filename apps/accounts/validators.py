from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class SimplePasswordValidator:
    """At least 8 characters, not only digits. Our own messages (Django's aren't in Uzbek)."""

    min_length = 8

    def validate(self, password, user=None):
        if len(password) < self.min_length:
            raise ValidationError(
                _("The password must be at least %(n)d characters long.") % {"n": self.min_length},
                code="password_too_short",
            )
        if password.isdigit():
            raise ValidationError(
                _("The password can't consist of digits only."), code="password_entirely_numeric"
            )
        if user is not None and getattr(user, "phone", "") and password in user.phone:
            raise ValidationError(
                _("The password can't be part of the phone number."), code="password_too_similar"
            )

    def get_help_text(self):
        return _("At least 8 characters, not only digits.")
