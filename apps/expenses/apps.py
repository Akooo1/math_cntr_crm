from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ExpensesConfig(AppConfig):
    name = "apps.expenses"
    label = "expenses"
    verbose_name = _("Expenses")

    def ready(self):
        from . import registry  # noqa: F401
