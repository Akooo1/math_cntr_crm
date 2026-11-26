"""Extension point: when a person is expected at work on a given day, from another module's
data (docs/SPEC.md §22). The students module registers teachers' first lesson of each day;
the staff module uses it for "Keldim". Staff and students sit on the same layer and can't
import each other, so the link lives here."""

import datetime as dt
from collections.abc import Callable

# provider(user_ids, start, end) -> {(user_id, day): expected start time}
_providers: list[Callable] = []


def register_day_start_provider(provider: Callable) -> None:
    if provider not in _providers:
        _providers.append(provider)


def day_starts(user_ids, start: dt.date, end: dt.date) -> dict[tuple[int, dt.date], dt.time]:
    """The earliest expected start per (user, day) over all providers."""
    ids = list(user_ids)
    out: dict[tuple[int, dt.date], dt.time] = {}
    if not ids:
        return out
    for provider in _providers:
        for key, t in (provider(ids, start, end) or {}).items():
            if key not in out or t < out[key]:
                out[key] = t
    return out
