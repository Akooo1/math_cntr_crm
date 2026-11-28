"""Sozlamalar → Mahsulotlar: books and items, with price history (Direktor)."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core import dates
from apps.core.settings_panel import Column, SettingsSection

from . import services
from .forms import CategoryForm, PriceForm, ProductForm
from .models import Category, Price, Product


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


def _delete_view(request, section, obj):
    """Confirm, then delete: a product never used, or a category without products."""
    from django.core.exceptions import ValidationError

    if request.method == "POST":
        try:
            if isinstance(obj, Product):
                services.delete_product(actor=request.user, product=obj)
            else:
                services.delete_category(actor=request.user, category=obj)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, _("Deleted."))
        return redirect("settings:section_list", slug=section.slug)
    return render(request, "store/confirm_delete.html", {"section": section, "obj": obj})


class ProductSection(SettingsSection):
    slug = "mahsulotlar"
    # The Direktor, or someone the Direktor gave "products and prices" (SPEC §22).
    permission = "store.catalog.manage"
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
        Column(gettext_lazy("Category"), lambda p: p.category.name if p.category else "—"),
        Column(gettext_lazy("Price"), _current_price, "money"),
        Column(gettext_lazy("Low-stock threshold"), lambda p: p.low_stock_threshold),
    ]
    actions = {
        "narx": (gettext_lazy("New price"), _price_view),
        "ochirish": (gettext_lazy("Delete"), _delete_view),
    }

    def get_queryset(self, request):
        return Product.objects.select_related("category")

    def action_visible(self, request, obj, key):
        return key != "ochirish" or not services.is_used(obj)  # used: hide it instead

    def save(self, request, form):
        d = form.cleaned_data
        if form.instance.pk:
            return services.update_product(
                actor=request.user,
                product=Product.objects.get(pk=form.instance.pk),
                category=d["category"],
                name=d["name"],
                low_stock_threshold=d["low_stock_threshold"],
                sort_order=d["sort_order"],
            )
        return services.create_product(
            actor=request.user,
            category=d["category"],
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


class CategorySection(SettingsSection):
    """Sozlamalar → Mahsulot turlari: the Direktor's own categories (SPEC §25)."""

    slug = "mahsulot-turlari"
    permission = "store.catalog.manage"
    title = gettext_lazy("Product categories")
    description = gettext_lazy("Kitoblar, daftarlar, ruchkalar...: names and how they are sold.")
    icon = "tag"
    order = 35
    group = gettext_lazy("Finance")
    model = Category
    form_class = CategoryForm
    audit_prefix = "store.category"
    columns = [
        Column(gettext_lazy("Name"), lambda c: c.name, primary=True),
        Column(gettext_lazy("Like books"), lambda c: c.is_book, "bool"),
        Column(gettext_lazy("Products"), lambda c: c.products.count()),
    ]
    actions = {"ochirish": (gettext_lazy("Delete"), _delete_view)}

    def action_visible(self, request, obj, key):
        return not obj.products.exists()

    def save(self, request, form):
        return services.save_category(actor=request.user, form=form)
