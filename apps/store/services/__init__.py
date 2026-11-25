"""Public write interface of the store module (docs/SPEC.md 17)."""

from .catalog import add_price, create_product, update_product
from .sales import give_book, give_books_to_group, reverse_sale, sell_items
from .stock import correct_stock, receive_stock

__all__ = [
    "add_price",
    "correct_stock",
    "create_product",
    "give_book",
    "give_books_to_group",
    "receive_stock",
    "reverse_sale",
    "sell_items",
    "update_product",
]
