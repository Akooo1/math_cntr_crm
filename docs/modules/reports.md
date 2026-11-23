# Reports module (`apps/reports`): Hisobotlar, Bosh sahifa

Read-only. Sits above billing and crm; nothing imports it. It never writes.

## Tables
None. Everything is computed from billing's ledger views (`billing_charge_net`,
`billing_allocation`, `billing_payment`) and crm's `crm_lead`.

## Reports
Registered in `definitions.py` with `core.reports.register_report(ReportDef(...))`. A report
is a function `build(user, Params) -> Result(columns, rows, totals, note)`; the screen, the
phone cards and the Excel export are generic.

| Slug | Report | Period |
|---|---|---|
| `oylar` | Charged and collected by month | yes |
| `filiallar` | By branch (charged, collected, unpaid now, overdue now) | yes |
| `kurslar` | By course (collected via FIFO allocation) | yes |
| `tolov-usullari` | By payment method (in, out, net, count) | yes |
| `qarzdorlik` | Debt by course (open, overdue, debtors) | no: current state |
| `lid-manbalar` | Lead conversion by source | yes |
| `lid-menejerlar` | Lead conversion by manager | yes |

Definitions: see docs/SPEC.md §12, Phase 5. Column kinds: `text`, `money`, `int`,
`percent` (0..1), `month`.

## Scoping
Every query starts from `scope_by_branch(...)` and then `apply_branch_filter(...)` with the
top-bar branch. A branch admin sees only their branches even with a forged filter
(tests: `apps/reports/tests/test_reports.py::TestBranchScope`).

## Dashboard
`registry.py` registers the `overview` widget (permission `reports.view`, order 0).
Numbers come from `dashboard.overview(user, branch_id)`.

## Permissions
| Code | Roles |
|---|---|
| `reports.view` | Direktor, Filial administratori |

## Events
Publishes none, consumes none.

## Adding a report (any module)
1. Write `build(user, params)` that uses the module's selectors, scoped by branch.
2. `register_report(ReportDef(key, title, description, permission, build, ...))` in the
   module's `ready()`.
3. The report appears in Hisobotlar with Excel export. Add its URL cases to
   `tests/test_permission_matrix.py` (they are generated from `reports()`), translate the
   strings, and test the numbers.
