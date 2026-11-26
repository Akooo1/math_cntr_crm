# Expenses and branch profit (`apps/expenses`)

Rules and owner decisions: docs/SPEC.md §20.

## Tables

- `expenses_category`: name, order, active.
- `expenses_expense` (append-only): kind (`expense` | `reversal`), branch (null = whole
  center), category, amount, spent_on, method (billing payment method counted in the Kassa,
  null = not from the cash desk), note, reverses / reason (reversals), created_by / at.
  CHECKs: amount > 0; a cash desk expense has a branch; a reversal points at an expense and
  has a reason.

## Services

`record()` (expenses.create; center-wide needs expenses.shared) and `reverse()`
(expenses.reverse, Direktor). Cash desk writes take `billing.services.cash.lock_day` and
check `is_day_closed`. Both audited (`expenses.expense.create` / `.reverse`).

## Integration

- Kassa: `register_cash_source("expenses")`: an expense is cash out, its reversal cash in.
- Profit report `filial-foydasi` (`core.reports`, Excel for free): reads billing payments,
  store's stock report (desk sales and purchase cost), salaries (lines, fixed lines,
  adjustments; draft for the open month) and expenses.
- Layer: `apps.expenses` sits above reports/salaries/telegram/store (`.importlinter`); its
  `domain` (the split) is pure.

## Permissions

expenses.view / .create (Direktor, branch administrator), .shared / .reverse / .profit
(Direktor). Screens: `/xarajatlar/` (period and category filters, total), `/xarajatlar/yangi/`,
`/xarajatlar/<id>/` (cancel form for the Direktor). Sozlamalar → Xarajat turlari.
