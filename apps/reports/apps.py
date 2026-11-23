from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ReportsConfig(AppConfig):
    """Read-only module: dashboards and report tables over every other module."""

    name = "apps.reports"
    label = "reports"
    verbose_name = _("Reports")

    def ready(self):
        from . import registry  # noqa: F401
