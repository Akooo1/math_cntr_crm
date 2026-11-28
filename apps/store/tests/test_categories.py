"""Product categories and deleting a product added by mistake (owner's request, SPEC §25)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, InternalError, connection, transaction

from apps.core import dates
from apps.store import services
from apps.store.models import Category, Price, Product
from tests.factories import page_text

pytestmark = pytest.mark.django_db


def books():
    return Category.objects.get(name="Kitoblar")


def items():
    return Category.objects.get(name="Mahsulotlar")


def new(director, category, name="Daftar"):
    return services.create_product(
        actor=director, category=category, name=name, price=5000, effective_from=dates.today()
    )


def test_existing_types_became_categories(director):
    assert books().is_book and not items().is_book
    p = services.create_product(
        actor=director, kind="book", name="Algebra", price=50_000, effective_from=dates.today()
    )
    assert (p.category, p.kind) == (books(), Product.Kind.BOOK)


def test_own_categories_follow_like_books(director):
    pens = Category.objects.create(name="Ruchkalar")
    tests_books = Category.objects.create(name="Test kitoblari", is_book=True)
    assert new(director, pens).kind == Product.Kind.ITEM
    book = new(director, tests_books, "DTM to'plami")
    assert book.kind == Product.Kind.BOOK
    services.update_product(actor=director, product=book, category=books())  # same behaviour
    with pytest.raises(ValidationError):
        services.update_product(actor=director, product=book, category=pens)


def test_delete_only_a_product_never_used(director, branch_a):
    wrong = new(director, items(), "Xato nom")
    used = new(director, items(), "Ishlatilgan")
    services.receive_stock(
        actor=director, branch=branch_a, product=used, quantity=5, received_on=dates.today()
    )
    services.delete_product(actor=director, product=wrong)
    assert not Product.objects.filter(pk=wrong.pk).exists()
    assert not Price.objects.filter(product_id=wrong.pk).exists()
    with pytest.raises(ValidationError):
        services.delete_product(actor=director, product=used)
    with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
        with connection.cursor() as cur:  # the database keeps a used product's prices
            cur.execute("DELETE FROM store_price WHERE product_id = %s", [used.pk])


def test_categories_rename_delete_and_rules(director, admin_a):
    pens = Category.objects.create(name="Ruchkalar")
    with pytest.raises(PermissionDenied):
        services.delete_category(actor=admin_a, category=pens)
    new(director, pens)
    with pytest.raises(ValidationError):  # still has a product
        services.delete_category(actor=director, category=pens)
    empty = Category.objects.create(name="Bo'sh")
    services.delete_category(actor=director, category=empty)
    assert not Category.objects.filter(pk=empty.pk).exists()


def test_screens(director, login):
    c = login(director)
    c.post("/sozlamalar/mahsulot-turlari/yangi/", {"name": "Yozuv", "sort_order": 30})
    cat = Category.objects.get(name="Yozuv")
    c.post(f"/sozlamalar/mahsulot-turlari/{cat.pk}/", {"name": "Kitoblar 2", "sort_order": 30})
    cat.refresh_from_db()
    assert cat.name == "Kitoblar 2"
    resp = c.post(
        "/sozlamalar/mahsulotlar/yangi/",
        {
            "category": cat.pk,
            "name": "Xato",
            "price": "1 000",
            "effective_from": dates.format_date(dates.today()),
            "low_stock_threshold": 0,
            "sort_order": 100,
        },
    )
    assert resp.status_code == 302
    p = Product.objects.get(name="Xato")
    assert f"/{p.pk}/ochirish/" in c.get("/sozlamalar/mahsulotlar/").content.decode()
    c.post(f"/sozlamalar/mahsulotlar/{p.pk}/ochirish/")
    assert not Product.objects.filter(name="Xato").exists()
    c.post(f"/sozlamalar/mahsulot-turlari/{cat.pk}/ochirish/")
    assert not Category.objects.filter(pk=cat.pk).exists()
    assert "Kitob" in page_text(c.get("/sozlamalar/mahsulot-turlari/"))
