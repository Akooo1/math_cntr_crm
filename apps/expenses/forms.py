from django import forms
from django.utils.translation import gettext_lazy as _

from apps.billing import selectors as billing_selectors
from apps.core import dates
from apps.core.forms import MoneyField, StyledForm, StyledModelForm, UzDateField
from apps.core.permissions import accessible_branch_ids, has_perm
from apps.settings.models import Branch

from .models import Category

CENTER = "markaz"
OUTSIDE = ""


class ExpenseForm(StyledForm):
    branch = forms.ChoiceField(label=_("Branch"))
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True), label=_("Category"), empty_label=None
    )
    amount = MoneyField(label=_("Amount"))
    spent_on = UzDateField(label=_("Date"))
    method = forms.ChoiceField(
        label=_("Paid from"),
        required=False,
        help_text=_("From the cash desk: the Kassa expects this much less cash that day."),
    )
    note = forms.CharField(label=_("Note"), required=False, widget=forms.Textarea)

    def __init__(self, *args, user, branch_filter=None, **kwargs):
        super().__init__(*args, **kwargs)
        ids = accessible_branch_ids(user)
        branches = Branch.objects.filter(is_active=True).order_by("name")
        if ids is not None:
            branches = branches.filter(pk__in=ids)
        choices = [(str(b.pk), b.name) for b in branches]
        if has_perm(user, "expenses.shared"):
            choices.append((CENTER, _("Whole center (split between branches)")))
        self.fields["branch"].choices = choices
        if branch_filter:
            self.fields["branch"].initial = str(branch_filter)
        self.fields["method"].choices = [
            *[
                (str(m.pk), _("Cash desk: %(m)s") % {"m": m.name})
                for m in billing_selectors.cash_methods_for_entry()
            ],
            (OUTSIDE, _("Not from the cash desk (bank, owner)")),
        ]
        self.fields["spent_on"].initial = dates.today()

    def clean(self):
        data = super().clean()
        raw = data.get("branch")
        data["branch"] = None if raw == CENTER else Branch.objects.filter(pk=raw).first()
        m = data.get("method")
        data["method"] = (
            billing_selectors.cash_methods_for_entry().filter(pk=m).first() if m else None
        )
        return data


class ReverseForm(StyledForm):
    reason = forms.CharField(label=_("Reason"), widget=forms.Textarea)


class CategoryForm(StyledModelForm):
    class Meta:
        model = Category
        fields = ["name", "sort_order"]
