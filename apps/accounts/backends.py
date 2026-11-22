from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

from apps.core import phone


class PhoneBackend(BaseBackend):
    """Login with phone + password. Inactive users can't log in."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        normalized = phone.normalize_or_none(username)
        if not normalized or not password:
            return None
        User = get_user_model()
        user = User.objects.filter(phone=normalized).first()
        if user is None:
            User().set_password(password)  # equalize timing with the existing-user path
            return None
        if user.is_active and user.check_password(password):
            return user
        return None

    def get_user(self, user_id):
        return get_user_model().objects.filter(pk=user_id, is_active=True).first()
