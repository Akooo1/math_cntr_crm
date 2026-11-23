"""FIFO allocation of payments to charges (docs/SPEC.md 6.4.6). Pure functions.

Recomputed from scratch for a student whenever their ledger changes, so it can't drift.
"""

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class OpenCharge:
    id: int
    due_date: dt.date
    order: tuple  # (created_at, id) tie-breaker
    net: int


@dataclass(frozen=True)
class Money:
    id: int
    paid_on: dt.date
    order: tuple
    amount: int


def allocate(
    charges: list[OpenCharge], payments: list[Money], refunded: int = 0
) -> tuple[list[tuple[int, int, int]], int]:
    """Returns ([(payment_id, charge_id, amount)], credit_left).

    `payments` are confirmed, not reversed. `refunded` (money paid back) is taken from the
    newest payments first, so it never funds a charge.
    """
    pool = sorted(payments, key=lambda p: (p.paid_on, p.order))
    available = [[p.id, p.amount] for p in pool]
    left = refunded
    for item in reversed(available):
        take = min(item[1], left)
        item[1] -= take
        left -= take
        if not left:
            break
    allocations: list[tuple[int, int, int]] = []
    queue = [item for item in available if item[1] > 0]
    qi = 0
    for charge in sorted(charges, key=lambda c: (c.due_date, c.order)):
        need = charge.net
        while need > 0 and qi < len(queue):
            pid, amt = queue[qi]
            take = min(amt, need)
            allocations.append((pid, charge.id, take))
            need -= take
            queue[qi][1] -= take
            if queue[qi][1] == 0:
                qi += 1
    credit = sum(item[1] for item in queue[qi:])
    return allocations, credit
