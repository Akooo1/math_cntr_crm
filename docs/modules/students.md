# Students module (`apps/students`) — O'quvchilar, Guruhlar, Davomat, Import

## Tables
`students_student`, `students_group`, `students_schedule_slot`, `students_lesson`,
`students_enrollment`, `students_enrollment_event`, `students_freeze`, `students_attendance`,
`students_import_batch`.

## Rules (docs/SPEC.md 6.3, 6.5, 12)
- A student belongs to one branch and can only join groups of that branch.
- Enroll / move / freeze / unfreeze / leave: each records an effective date and a reason
  (optional only for enroll), writes `students_enrollment_event` and an audit row, and
  publishes an event. Windows are `[start, end)`.
- Lessons are generated from the weekly schedule (`generate_lessons`, idempotent). Open-ended
  groups get 90 days ahead, which the daily job rolls forward from phase 5.
- Attendance is informational only. Teachers mark their own groups within the edit window.
- The Excel import validates the whole file, reports errors per row in Uzbek, and commits
  everything in one transaction or nothing.

## Permissions
| Code | Roles |
|---|---|
| `students.view`, `groups.view` | all four roles (O'qituvchi: own groups and their students only) |
| `students.create` | Direktor, Filial administratori, Sotuv menejeri (manager: via lead conversion only) |
| `students.manage`, `groups.manage`, `import.run` | Direktor, Filial administratori |
| `attendance.mark` | Direktor, Filial administratori, O'qituvchi |

## Extension points (for billing and later modules)
- `register_enrollment_extension(ext)`: confirmation step + action inside the transaction.
- `register_profile_panel(ProfilePanel(...))`: a panel on the student profile.
- `register_list_badge(fn)`: a badge in the student list (billing: payment status).
- `register_import_kind(ImportKind(...))`: e.g. opening balances (billing).

## Events (outbox)
`students.student_created`, `students.enrollment_created`, `students.enrollment_moved`,
`students.enrollment_frozen`, `students.enrollment_unfrozen`, `students.enrollment_left`,
`students.lesson_held`.

## URLs
`/oquvchilar/`, `/guruhlar/`, `/davomat/` (today's lessons), `/import/`. All are in the
permission matrix.
