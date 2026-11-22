from django.utils.translation import gettext_lazy as _

from apps.core.system_settings import SettingDef, register_setting

from . import sections  # noqa: F401 - registers Sozlamalar sections

register_setting(
    SettingDef(
        key="billing.rounding_step",
        label=_("Rounding of computed amounts"),
        help_text=_(
            "Prorated amounts, percent discounts and installment parts are rounded to this."
        ),
        default=1000,
        choices=((1, _("1 so'm")), (100, _("100 so'm")), (1000, _("1 000 so'm"))),
        order=10,
    )
)
register_setting(
    SettingDef(
        key="billing.monthly_due_day",
        label=_("Monthly fee due day"),
        help_text=_("Day of the month the monthly fee is due."),
        default=10,
        min_value=1,
        max_value=28,
        order=20,
    )
)
register_setting(
    SettingDef(
        key="billing.backdate_days",
        label=_("Payment backdating window (days)"),
        help_text=_("How many days back a payment date may be. Closed days are always locked."),
        default=3,
        min_value=0,
        max_value=31,
        order=30,
    )
)
register_setting(
    SettingDef(
        key="billing.grace_days",
        label=_("Grace period before debt (days)"),
        help_text=_("Days after the due date before a student appears in the debtors list."),
        default=0,
        min_value=0,
        max_value=60,
        order=40,
    )
)
