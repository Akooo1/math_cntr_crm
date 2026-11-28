"""Public write interface of the store module (docs/SPEC.md 17)."""

from .catalog import (
    add_price,
    create_product,
    default_category,
    delete_category,
    delete_product,
    is_used,
    save_category,
    update_product,
)
from .sales import give_book, give_books_to_group, reverse_sale, sell_items
from .stock import correct_stock, receive_stock

__all__ = [
    "add_price",
    "correct_stock",
    "create_product",
    "default_category",
    "delete_category",
    "delete_product",
    "give_book",
    "give_books_to_group",
    "is_used",
    "receive_stock",
    "reverse_sale",
    "save_category",
    "sell_items",
    "update_product",
]
