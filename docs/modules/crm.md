# CRM module (`apps/crm`) — Lidlar

## Tables
`crm_lead_source`, `crm_lead_stage`, `crm_refusal_reason` (reference data, edited in Sozlamalar),
`crm_lead`, `crm_lead_activity` (history, kept forever), `crm_follow_up_task`, `crm_trial_lesson`.

## Rules (docs/SPEC.md 6.2)
- New leads start in the `new` stage. Every change writes a `crm_lead_activity` row.
- Duplicate check on create/edit: normalized phone and extra phone against leads and
  students in all branches. Other branches are named only. Saving needs "Baribir saqlash".
- `won` only through conversion; `lost` only with a refusal reason (open tasks are closed);
  a lost lead can be reopened (to `contacted`). Converted leads can't change stage.
- Booking a trial moves `new` / `contacted` / custom stages to `trial_booked`; marking it
  attended moves to `trial_attended`. Trial lessons are free.
- `next_follow_up_at` = earliest open task, recalculated on every task change.
- Conversion creates the student via `students.services.create_student`, links it, moves the
  lead to `won`, closes its tasks and writes the audit row `crm.lead.convert`.

## Permissions
| Code | Roles |
|---|---|
| `crm.leads.view`, `crm.leads.edit`, `crm.leads.convert` | Direktor, Filial administratori, Sotuv menejeri |
| `crm.tasks.view_all` | Direktor, Filial administratori |

O'qituvchi has no CRM access. Everything is branch-scoped; other branches return 404.

## Events published (outbox)
`crm.lead_created`, `crm.trial_lesson_booked`, `crm.lead_converted`. A future Telegram module
can send "trial lesson tomorrow" reminders from `crm.trial_lesson_booked`.

## URLs
`/lidlar/` board (phone: stage chips + list), `/lidlar/yangi/`, `/lidlar/<id>/` card,
`/vazifalar/` my tasks, `/sinov-darslari/` trial lessons. All are in the permission matrix.
