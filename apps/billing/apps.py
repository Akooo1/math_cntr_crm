from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BillingConfig(AppConfig):
    name = "apps.billing"
    label = "billing"
    verbose_name = _("Payments")

    def ready(self):
        from . import registry  # noqa: F401
