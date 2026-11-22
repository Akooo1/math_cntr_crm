from django.utils.translation import gettext_lazy as _

from apps.core.settings_panel import Column, SettingsSection, register_section

from .forms import LeadSourceForm, LeadStageForm, RefusalReasonForm
from .models import LeadSource, LeadStage, RefusalReason

GROUP_CRM = _("Leads")


class LeadSourceSection(SettingsSection):
    slug = "lid-manbalari"
    title = _("Lead sources")
    description = _("Where leads come from: Instagram, Telegram, phone calls, walk-ins.")
    icon = "funnel"
    order = 60
    group = GROUP_CRM
    model = LeadSource
    form_class = LeadSourceForm
    audit_prefix = "crm.lead_source"
    columns = [
        Column(_("Name"), lambda s: s.name, primary=True),
        Column(_("Order"), lambda s: s.sort_order),
    ]


class LeadStageSection(SettingsSection):
    slug = "lid-bosqichlari"
    title = _("Lead stages")
    description = _(
        "Pipeline stages. The main stages can be renamed and reordered; extra stages can be added."
    )
    icon = "list"
    order = 61
    group = GROUP_CRM
    model = LeadStage
    form_class = LeadStageForm
    audit_prefix = "crm.lead_stage"
    columns = [
        Column(_("Name"), lambda s: s, primary=True, kind="stage"),
        Column(_("Stage type"), lambda s: s.get_kind_display()),
        Column(_("Order"), lambda s: s.sort_order),
    ]

    def can_toggle(self, request, obj):
        return not obj.is_system


class RefusalReasonSection(SettingsSection):
    slug = "rad-sabablari"
    title = _("Refusal reasons")
    description = _("Reasons a lead refused, used for the Refused stage.")
    icon = "x-circle"
    order = 62
    group = GROUP_CRM
    model = RefusalReason
    form_class = RefusalReasonForm
    audit_prefix = "crm.refusal_reason"
    columns = [
        Column(_("Name"), lambda s: s.name, primary=True),
        Column(_("Order"), lambda s: s.sort_order),
    ]


for section in (LeadSourceSection(), LeadStageSection(), RefusalReasonSection()):
    register_section(section)
