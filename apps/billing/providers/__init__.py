from .manual import ManualProvider, OpeningBalanceProvider

_providers = {p.code: p for p in (ManualProvider(), OpeningBalanceProvider())}


def register_provider(provider) -> None:
    _providers[provider.code] = provider


def get_provider(code: str):
    return _providers[code]


def selectable_providers():
    return [p for p in _providers.values() if not p.is_system]
