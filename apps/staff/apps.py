from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class StaffConfig(AppConfig):
    name = "apps.staff"
    label = "staff"
    verbose_name = _("Staff attendance")

    def ready(self):
        from . import registry  # noqa: F401
