from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CrmConfig(AppConfig):
    name = "apps.crm"
    label = "crm"
    verbose_name = _("Leads")

    def ready(self):
        from . import registry  # noqa: F401
