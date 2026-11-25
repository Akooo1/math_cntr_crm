from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core import dates
from apps.core.forms import MoneyField, StyledForm, StyledModelForm, UzDateField

from .models import Product


class ProductForm(StyledModelForm):
    """New product with its first price; on edit the type and price fields are hidden
    (prices change only through a new price row)."""

    price = MoneyField(label=_("Price"), min_value=1, required=False)
    effective_from = UzDateField(label=_("Effective from"), required=False)

    class Meta:
        model = Product
        fields = ["kind", "name", "low_stock_threshold", "sort_order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields["kind"]
            del self.fields["price"]
            del self.fields["effective_from"]
        else:
            self.fields["price"].required = True
            self.fields["effective_from"].required = True
            self.fields["effective_from"].initial = dates.today()


class PriceForm(StyledForm):
    amount = MoneyField(label=_("New price"), min_value=1)
    effective_from = UzDateField(label=_("Effective from"))
    note = forms.CharField(label=_("Note"), required=False, max_length=255)


class ReceiveForm(StyledForm):
    product = forms.ModelChoiceField(label=_("Product"), queryset=Product.objects.none())
    quantity = forms.IntegerField(label=_("Quantity"), min_value=1)
    received_on = UzDateField(label=_("Date"))
    purchase_cost = MoneyField(
        label=_("Purchase cost (total)"),
        required=False,
        help_text=_("What the whole delivery cost. Optional; needed for the margin."),
    )
    note = forms.CharField(label=_("Note"), required=False, max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(is_active=True)
        self.fields["received_on"].initial = dates.today()


class CorrectionForm(StyledForm):
    product = forms.ModelChoiceField(label=_("Product"), queryset=Product.objects.none())
    counted = forms.IntegerField(
        label=_("Counted quantity"),
        min_value=0,
        help_text=_("How many are actually on the shelf now."),
    )
    reason = forms.CharField(label=_("Reason"), widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.all()


class ReverseForm(StyledForm):
    reason = forms.CharField(label=_("Reason"), widget=forms.Textarea)
