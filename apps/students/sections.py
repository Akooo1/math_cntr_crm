from django.utils.translation import gettext_lazy as _

from apps.core.settings_panel import Column, SettingsSection, register_section

from .forms import LeaveReasonForm
from .models import LeaveReason


class LeaveReasonSection(SettingsSection):
    slug = "ketish-sabablari"
    title = _("Leave reasons")
    description = _("Why students leave a group. Chosen when a student leaves; see the report.")
    icon = "x-circle"
    order = 45
    group = _("Courses and prices")
    model = LeaveReason
    form_class = LeaveReasonForm
    audit_prefix = "students.leave_reason"
    columns = [
        Column(_("Name"), lambda s: s.name, primary=True),
        Column(_("Order"), lambda s: s.sort_order),
    ]


register_section(LeaveReasonSection())
