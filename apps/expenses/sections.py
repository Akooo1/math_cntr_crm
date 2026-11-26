from django.utils.translation import gettext_lazy as _

from apps.core.settings_panel import Column, SettingsSection, register_section

from .forms import CategoryForm
from .models import Category


class CategorySection(SettingsSection):
    slug = "xarajat-turlari"
    title = _("Expense categories")
    description = _("Rent, utilities, advertising and other kinds of expenses.")
    icon = "tag"
    order = 66
    group = _("Finance")
    model = Category
    form_class = CategoryForm
    audit_prefix = "expenses.category"
    columns = [
        Column(_("Name"), lambda s: s.name, primary=True),
        Column(_("Order"), lambda s: s.sort_order),
    ]


register_section(CategorySection())
