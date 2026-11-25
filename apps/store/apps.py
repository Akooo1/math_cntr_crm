from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class StoreConfig(AppConfig):
    name = "apps.store"
    label = "store"
    verbose_name = _("Sales")

    def ready(self):
        from . import registry  # noqa: F401
