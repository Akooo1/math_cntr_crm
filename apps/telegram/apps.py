from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TelegramConfig(AppConfig):
    name = "apps.telegram"
    label = "telegram"
    verbose_name = _("Telegram bot")

    def ready(self):
        from . import handlers, registry  # noqa: F401
