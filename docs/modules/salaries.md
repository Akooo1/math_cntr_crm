# Salaries module (`apps/salaries`): Maoshlar, Maoshim

Teacher salaries as a share of the money students actually paid. Rules: docs/SPEC.md §13.
Sits on the same layer as `reports`, above billing and students. Nothing imports it except
the demo seed.

## Tables
`salaries_rate`, `salaries_month`, `salaries_line`, `salaries_payout` (append-only,
`mm_forbid_update_delete`), `salaries_adjustment` (deletable only while its month is open;
triggers `salaries_adjustment_locked` and `salaries_adjustment_closed_month`).

## How a month is computed
`selectors.draft(month)` reads `billing_allocation` (charges with a group, payments from the
start month on), subtracts what closed months already froze (`salaries_line`), and hands the
differences to `domain/calc.draft_lines()`. Money is rounded with
`billing.services.percent_of`. `services.close_month()` freezes the result, under a
PostgreSQL advisory lock.

## Screens
| URL | Who |
|---|---|
| `/maosh/?oy=MM.YYYY` (+ `&excel=1`) | Direktor: all teachers for a month, close month |
| `/maosh/oqituvchi/<id>/?oy=` | Direktor: one sheet, bonuses/deductions, payout |
| `/maoshim/` (`?oy=`) | O'qituvchi: own months and sheets |
| `/sozlamalar/stavkalar/` | Direktor: teacher rates with history |

## Permissions
| Code | Roles |
|---|---|
| `salaries.manage` | Direktor |
| `salaries.view_own` | O'qituvchi |

## Settings
`salaries.default_rate_bp` (5 000), `salaries.start_month` (YYYYMM, 202612).

## Events
Publishes none, consumes none. It reads billing's allocation, so it never misses a payment,
reversal or refund.

## Audit
`salaries.rate.create`, `salaries.month.close`, `salaries.adjustment.create` / `.delete`,
`salaries.payout.create` / `.cancel`.
