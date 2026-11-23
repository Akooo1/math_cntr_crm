# Staff module (`apps/staff`): Xodimlar davomati, "Keldim"

Morning arrival check-in with the phone's GPS. Rules: docs/SPEC.md §14. Sits on the same
layer as `students` (depends on core, accounts, settings only).

## Tables
`staff_branch_location`, `staff_schedule`, `staff_checkin` (append-only trigger; unique per
user and day).

## How "Keldim" works
1. `static/js/app.js` (`[data-geolocate]`) asks the browser for the position (needs HTTPS
   on phones) and posts `lat`, `lng`, `accuracy` to `/keldim/`.
2. `services.check_in()` refuses readings less precise than 200 m, finds the nearest of the
   employee's branches (`domain/rules.py`, haversine), refuses if outside its radius, stamps
   the server time, computes late minutes from the schedule and the grace setting, audits
   and publishes `staff.checked_in` to the outbox (Telegram, phase 8).
3. GPS can be faked with special apps. IP and browser are stored to help spot that.

## Screens
| URL | Who |
|---|---|
| Bosh sahifa "Keldim" card | Filial administratori, Sotuv menejeri, O'qituvchi |
| `/xodimlar-davomati/?sana=DD.MM.YYYY` | Direktor: board, manual entry |
| `/hisobotlar/xodimlar-davomati/` | Direktor: monthly report, Excel |
| `/sozlamalar/filial-joylashuvi/`, `/sozlamalar/ish-vaqti/` | Direktor |

## Permissions
| Code | Roles |
|---|---|
| `staff.checkin` | Filial administratori, Sotuv menejeri, O'qituvchi |
| `staff.attendance.view` | Direktor |

## Settings
`staff.grace_minutes` (10).

## Events
Publishes `staff.checked_in` (outbox). Consumes none.

## Known limits
- Missed workdays in the report use the employee's current schedule (schedule history is
  not kept).
- A wrong check-in can't be edited or deleted (append-only); the audit log shows who did it.
