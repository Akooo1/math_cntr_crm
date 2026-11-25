"""Sozlamalar → Mahsulotlar: books and items, with price history (Direktor)."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core import dates
from apps.core.settings_panel import Column, SettingsSection

from . import services
from .forms import PriceForm, ProductForm
from .models import Price, Product


def _current_price(product):
    p = (
        Price.objects.filter(product=product, effective_from__lte=dates.today())
        .order_by("-effective_from", "-created_at", "-id")
        .first()
    )
    return p.amount if p else None


def _price_view(request, section, product):
    form = PriceForm(
        data=request.POST if request.method == "POST" else None,
        initial={"effective_from": dates.today()},
    )
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        services.add_price(
            actor=request.user,
            product=product,
            amount=d["amount"],
            effective_from=d["effective_from"],
            note=d["note"],
        )
        messages.success(request, _("Saved."))
        return redirect("settings:section_edit", slug=section.slug, pk=product.pk)
    return render(
        request,
        "store/price_form.html",
        {"section": section, "product": product, "form": form, "title": product.name},
    )


class ProductSection(SettingsSection):
    slug = "mahsulotlar"
    title = gettext_lazy("Products")
    description = gettext_lazy("Books and items sold at the desk: names, prices, low stock.")
    icon = "tag"
    order = 36
    group = gettext_lazy("Finance")
    model = Product
    form_class = ProductForm
    audit_prefix = "store.product"
    form_template = "store/product_form.html"
    columns = [
        Column(gettext_lazy("Name"), lambda p: p.name, primary=True),
        Column(gettext_lazy("Type"), lambda p: p.get_kind_display()),
        Column(gettext_lazy("Price"), _current_price, "money"),
        Column(gettext_lazy("Low-stock threshold"), lambda p: p.low_stock_threshold),
    ]
    actions = {"narx": (gettext_lazy("New price"), _price_view)}

    def save(self, request, form):
        d = form.cleaned_data
        if form.instance.pk:
            return services.update_product(
                actor=request.user,
                product=form.instance,
                name=d["name"],
                low_stock_threshold=d["low_stock_threshold"],
                sort_order=d["sort_order"],
            )
        return services.create_product(
            actor=request.user,
            kind=d["kind"],
            name=d["name"],
            price=d["price"],
            effective_from=d["effective_from"],
            low_stock_threshold=d["low_stock_threshold"],
            sort_order=d["sort_order"],
        )

    def toggle(self, request, obj):
        return services.update_product(actor=request.user, product=obj, is_active=not obj.is_active)

    def extra_context(self, request, obj):
        if obj is None:
            return {}
        return {"prices": obj.prices.select_related("created_by"), "today": dates.today()}
