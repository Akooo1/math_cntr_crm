class ManualProvider:
    """Money taken by staff: cash, card terminal, bank transfer."""

    code = "manual"
    is_online = False
    is_system = False

    def validate_manual_entry(self, data: dict) -> None:
        return None


class OpeningBalanceProvider:
    """Internal: credit carried over from the old lists by the Excel import."""

    code = "opening_balance"
    is_online = False
    is_system = True

    def validate_manual_entry(self, data: dict) -> None:
        raise ValueError("opening balances are created by the import only")
