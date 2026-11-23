from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SalariesConfig(AppConfig):
    name = "apps.salaries"
    label = "salaries"
    verbose_name = _("Salaries")

    def ready(self):
        from . import registry  # noqa: F401
