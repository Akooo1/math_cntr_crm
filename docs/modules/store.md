# Store module (`apps/store`): Savdo, Ombor, Kitob berish

Books handed to students and items sold at the desk (water, pens, notebooks), with
per-branch stock. Rules and the owner's answers: docs/SPEC.md §17. Sits on the same layer
as `reports | salaries | telegram`. It depends on `billing` (ledger, payment methods, the
Kassa extension point), `students`, `settings` and `core`. Nothing imports it except `demo`.

## Tables
| Table | Notes |
|---|---|
| `store_product` | kind `book` / `item`, name (unique per kind), low-stock threshold, active, order. Global catalog; never deleted. |
| `store_price` | Append-only price history (`effective_from`). The price in force on the sale date is copied into the sale line. |
| `store_stock_movement` | Append-only. `receipt` (+, optional total purchase cost), `sale` (−), `sale_reversal` (+), `correction` (±, reason). Sign CHECKs per kind. |
| `store_sale` | One basket or one book. `paid` (method, Kassa) or `on_account` (book only, `charge_id` → `billing_charge`, student). Append-only; closed-day trigger for paid sales. |
| `store_sale_line` | product, quantity, price row, unit price, amount (CHECK `amount = unit_price × quantity`). Append-only. |
| `store_sale_reversal` | One per sale, dated the day it's made, reason. Append-only; closed-day trigger when the sale was paid. |
| `store_stock_on_hand` (view) | `Σ quantity` per (branch, product). **Stock is never stored.** |

## Money and stock rules (where they live)
- `domain/stock.py`: on hand, basket merge, availability check, correction delta, low-stock flag.
- `domain/margin.py`: weighted average unit cost (None when a receipt has no cost), exact
  cost of the units sold. Selectors round it with `billing.services.round_amount`, the one
  money rounding function.
- `services/sales.py`:
  - `sell_items`: items only, no student, today, a cash-report method.
  - `give_book`: pay now (store sale, Kassa) or pay later (a `manual` charge through
    `billing.services.ledger.create_charge`, due `today + store.book_due_days`, no group,
    so salaries never count it).
  - `give_books_to_group`: one book and one charge per ticked student; stock is checked
    for all of them first.
  - `reverse_sale`: Direktor only, the whole sale, stock back, Kassa out for paid sales; for
    a book on account a `cancellation` adjustment brings the charge to 0.
- Concurrency: every sale row-locks its products (`SELECT … FOR UPDATE`, id order) before
  reading stock, so the last unit can't be sold twice. Paid sales and their reversals also
  take billing's cash-day lock (`billing.services.cash.lock_day`) before checking the close.

## Kassa extension point (in billing, SPEC 17.4)
`billing.services.cash.register_cash_source(CashSource(code, label, lines, active_days))`.
`lines(branch_id, day)` returns `CashLine`s (method, in/out, amount, time, who, text, link).
`day_report()` adds them to the per-method totals and to a per-source breakdown
(`report["sources"]`, `report["extra_lines"]`); `close_day()` stores the breakdown in the
snapshot; the Kassa page and its Excel list the lines; `unclosed_days()` also flags days that
only have store sales. The store registers the source `store` ("Savdo") in `registry.py`.

## Screens
| URL | Who |
|---|---|
| `/savdo/` | Direktor, Filial administratori: tap tiles → basket → method → "Sotish"; today's sales |
| `/savdo/jurnal/?dan=&gacha=` | Same: sales journal |
| `/savdo/<id>/`, `/savdo/<id>/bekor-qilish/` | Sale; cancellation is Direktor only |
| `/ombor/`, `/ombor/mahsulot/<id>/` | Stock per branch, movement history |
| `/ombor/kirim/` | Direktor, Filial administratori (own branch) |
| `/ombor/tuzatish/` | Direktor (enter the counted quantity and a reason) |
| `/kitob-berish/<student_id>/` | Direktor, Filial administratori; also the "Kitoblar" panel on the student card |
| `/guruhga-kitob/?guruh=<id>` | Direktor, Filial administratori |
| `/sozlamalar/mahsulotlar/` | Direktor: products, "Yangi narx", price history |
| `/hisobotlar/ombor-savdo/` | Report "Ombor va savdo" with Excel |
| Bosh sahifa "Kam qoldi" card | Direktor, Filial administratori |

The Direktor with "all branches" in the top bar picks a branch first on Savdo and Ombor.

## Permissions
| Code | Roles |
|---|---|
| `store.catalog.manage` | Direktor |
| `store.stock.receive` | Direktor, Filial administratori |
| `store.stock.correct` | Direktor |
| `store.sell` | Direktor, Filial administratori |
| `store.sale.reverse` | Direktor |
| `store.view` | Direktor, Filial administratori |
| `store.cost.view` | Direktor (purchase cost and margin columns) |

## Settings
`store.book_due_days` (7), in Umumiy sozlamalar.

## Report "Ombor va savdo"
Per product for the period and branch:
- Kirim
- Sotildi (net of cancellations; books included)
- Qoldiq at the end of the period
- Savdo summasi, and the part that is pay-later
- Direktor only: Xarid narxi (cost of the units sold, weighted average per branch) and
  Foyda. Both show "—" when any delivery in scope had no cost.
- Kam qoldi (now)

Store sales are **not** Tushum: the "collected" reports stay student payments only (Q-S10).

## Audit
`store.product.create` / `.update`, `store.price.create`, `store.stock.receive`,
`store.stock.correct` (before/after on hand), `store.sale.create`, `store.book.give`,
`store.sale.reverse`, plus billing's own `billing.charge.create` / `billing.charge.adjust`
for books on account.

## Events
Publishes `store.sale_recorded` and `store.sale_reversed` (outbox). Consumes none.

## Known limits
- One price for all branches (Q-S1). A per-branch price would be a nullable branch on
  `store_price`.
- No receipt (Chek) for store sales (Q-S9).
- A book returned in good condition (not a mistake) has no own flow; the Direktor cancels the
  sale with the reason.
