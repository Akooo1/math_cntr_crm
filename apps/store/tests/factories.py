"""Store test helpers. Clock (from billing helpers): Monday 16.11.2026 10:00 Tashkent."""

import datetime as dt

import pytest

from apps.store import services
from apps.store.models import Product

D = dt.date
TODAY = D(2026, 11, 16)


def make_product(director, name, price, *, kind=Product.Kind.ITEM, threshold=0):
    return services.create_product(
        actor=director,
        kind=kind,
        name=name,
        price=price,
        effective_from=D(2026, 1, 1),
        low_stock_threshold=threshold,
    )


def receive(actor, branch, product, qty, cost=None, day=TODAY):
    return services.receive_stock(
        actor=actor,
        branch=branch,
        product=product,
        quantity=qty,
        received_on=day,
        purchase_cost=cost,
    )


@pytest.fixture
def shop(clock, director, branch_a):
    """Small water 3 000, big water 5 000 (threshold 3), a book 60 000; stock in branch A."""
    small = make_product(director, "0,5 L suv", 3_000)
    big = make_product(director, "1 L suv", 5_000, threshold=3)
    book = make_product(director, "Algebra 7", 60_000, kind=Product.Kind.BOOK)
    receive(director, branch_a, small, 20, cost=40_000)
    receive(director, branch_a, big, 5)
    receive(director, branch_a, book, 10, cost=400_000)
    return {"small": small, "big": big, "book": book}
