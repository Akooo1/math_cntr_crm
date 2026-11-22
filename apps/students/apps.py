from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class StudentsConfig(AppConfig):
    name = "apps.students"
    label = "students"
    verbose_name = _("Students")

    def ready(self):
        from . import registry  # noqa: F401
