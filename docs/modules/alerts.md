# Early warnings (`apps/alerts`)

Rules and owner decisions: docs/SPEC.md §19.

## Table

`alerts_task`: kind (`absence` | `debt` | `lead`), branch, student / group / lead (by kind),
assigned_to (null = the branch's administrators), details (JSON: missed count; overdue
amount, days, oldest due date; working hours), key (unique: one task per cause), due_at
(leads), created_at, closed_at / closed_by / closed_how (`done` by a person, `resolved` by
the job). Not money: a plain table, no ledger rules.

## Job

`manage.py run_alerts` (deploy/crontab, every 15 minutes). Idempotent. Reads
`students_attendance`, `billing.selectors.overdue_summary()` (new, system-wide) and
`crm_lead` / `crm_lead_activity`. Pure rules in `apps/alerts/domain` (working-hours deadline,
absence streak, debt reminder round) with their own tests.

## Events

Publishes `alerts.created` (in-process). The telegram module subscribes and sends lead
warnings to the manager's staff chat after commit (message kind `alert`).

## Permissions, screens, settings

- `alerts.view` (all roles); visibility per kind in `selectors.visible_tasks` (SPEC §19.3).
- `/ogohlantirishlar/` with chips by kind; `…/<id>/bajarildi/` (toast with undo) and
  `…/<id>/qayta-ochish/`. Dashboard tile with counts.
- Settings `alerts.*` in Umumiy sozlamalar (Direktor).

## Layer

`apps.alerts` sits between billing/crm and reports/salaries/telegram/store
(`.importlinter`); its `domain` package is pure.
