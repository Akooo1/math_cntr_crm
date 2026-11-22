"""Payment provider interface (docs/SPEC.md 4.4).

Module 1 ships the manual provider (cash, card terminal, bank transfer entered by staff)
and an internal provider for opening balances. Click, Payme and Uzum will implement the
online part of this interface later.
"""

from typing import Protocol


class PaymentProvider(Protocol):
    code: str
    is_online: bool
    is_system: bool  # internal provider: not selectable for payment entry, not editable

    def validate_manual_entry(self, data: dict) -> None: ...

    # Online providers only (not implemented in module 1):
    # def create_invoice(self, student, amount): ...
    # def handle_webhook(self, request): ...
