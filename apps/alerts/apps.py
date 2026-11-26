from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AlertsConfig(AppConfig):
    name = "apps.alerts"
    label = "alerts"
    verbose_name = _("Warnings")

    def ready(self):
        from . import registry  # noqa: F401
