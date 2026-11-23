# CLAUDE.md — Matematika Markazi operations platform

Read `docs/SPEC.md` before any work. It is the source of truth for scope, data model and business rules. This file holds the conventions every session and every future module must follow.

## Project status

- Module 1 (CRM + students + billing), built in phases 0–5. Each phase ends with a stop: report what was built, how to run it and what to check, then **wait for the owner's approval** before starting the next phase.
- Current phase: **6 done** (teacher salaries, Module 2). Next: phase 7 (staff arrival check-in with GPS, manual deletion of old notification records), phase 8 (Telegram bot: Direktor notifications, debt reminders to parents), phase 9 (go-live). Update this line at the end of each phase.

## Ask the owner before

- adding any paid service or external API (including off-site backup storage)
- changing the data model after it is approved (new tables or columns in an existing module, changed constraints or semantics)
- deleting files or data
- deciding any money rule not covered by `docs/SPEC.md` section 6 or 9. Do not guess. Ask.

## Stack

Python 3.12, Django 5.2 LTS, PostgreSQL 17, Django templates + HTMX 2 + Alpine.js 3 + Tailwind CSS 4 (standalone CLI, no Node at runtime), openpyxl, supercronic, gunicorn, Caddy, uv, pytest + pytest-django + factory_boy, import-linter. Deployed with Docker Compose.

## Commands

```bash
docker compose up                              # full local stack; seeds demo data on an empty DB
uv run pytest                                  # all tests (needs PostgreSQL; POSTGRES_* env vars)
uv run pytest apps/billing                     # one module
uv run lint-imports                            # module layer contracts (.importlinter)
uv run ruff check . && uv run ruff format .    # lint + format
uv run python manage.py makemigrations --check --dry-run
scripts/i18n.sh                                # extract UI strings into locale/uz/.../django.po + compile
scripts/i18n.sh --check                        # CI: fail if strings changed and were not extracted
uv run python manage.py seed_demo              # demo data (apps/demo), idempotent
npm run build:css                              # Tailwind -> static/dist/app.css (dev compose runs a watcher)
```

## Layout and module boundaries

```
config/   apps/{core,accounts,settings,crm,students,billing,reports,salaries,demo}/   templates/   static/   locale/   scripts/   docs/   tests/
```

`apps/demo` holds the demo seed command only; it sits above every module and nothing imports it.

Dependency direction (enforced by `.importlinter`; CI fails on violations):

```
core ← accounts ← settings ← crm, students ;  students ← billing ← reports, salaries ;  crm → students
```

- Import another module only through `services`, `selectors`, `events`, or `models` (models only for FK targets and types).
- A lower module never imports a higher one. To trigger behavior upward, publish a domain event (`events.py`) and let the higher module subscribe (`handlers.py`).
- `reports` never writes.
- The `settings` app has the label `center_settings`. Don't confuse it with `django.conf.settings`.

Inside a module:

- `domain/`: pure functions, no Django imports. All money math lives here.
- `services/`: the **only** code that writes. Each service checks the permission, runs in `transaction.atomic()`, takes the needed locks, validates, writes, calls `core.audit.record(...)` and publishes events.
- `selectors.py`: reads. Each selector takes `user` and starts from `scoped_queryset(...)`.
- `policies.py`: permission rules.
- `views.py` stays thin: parse input, call one service or selector, render. No business rules in views, forms or templates.
- `registry.py`: nav items, settings sections, dashboard widgets, reports, enrollment extensions. Registered in `AppConfig.ready()`.

## Money rules (non-negotiable)

- Amounts are **whole so'm in `bigint`**. Never use `float` or `Decimal` for stored money. Ratios (proration, percents) are computed with integers or `fractions.Fraction` and rounded with `billing.domain.rounding.round_amount()`. Nowhere else.
- Percents are stored in **basis points** (10% = 1000).
- The ledger is **append-only**: charges, charge discounts, charge adjustments, payments, cash day closes and the audit log are never UPDATEd or DELETEd. A PostgreSQL trigger enforces this. Corrections are new rows (adjustment, reversal, refund) with a reason.
- **The balance is never stored.** It is always computed from the ledger (`billing_student_balance` view / `billing.selectors.balance`). Never add a balance column.
- `billing_allocation` is a derived cache. Only `billing.services.allocation.rebuild_for_student()` writes it, under a row lock on the student.
- Price rows are immutable. A price change is a new row with `effective_from`. Issued charges copy the price and never change when prices change.
- Any amount that differs from the system's suggestion requires a reason. Store both `suggested_amount` and the final amount.
- Reversals and refunds are Direktor only. A closed cash day accepts no new payment, reversal or refund dated that day. This is enforced in the service **and** by a trigger.
- Every billing change ships with tests. Billing coverage stays ≥ 95%.

## Dates, time, phones

- `TIME_ZONE = "Asia/Tashkent"`, `USE_TZ = True`. Business dates are `date` columns. Use `core.dates.today()` and `core.dates.now()`. Never call `date.today()`, `datetime.now()` or `timezone.now().date()` directly.
- Display: dates as `DD.MM.YYYY` (`|sana`), date-times as `DD.MM.YYYY HH:MM`. Inputs accept `DD.MM.YYYY`.
- Phones are stored as E.164 `+998XXXXXXXXX`. Normalize with `core.phone.normalize()`. Display `+998 90 123 45 67` (`|telefon`).

## UI text and i18n

- **No hard-coded user-visible text.** Use `{% translate %}`, `{% blocktranslate %}`, `gettext_lazy` and `ngettext`. This includes form errors, messages, emails, Excel headers and receipt text.
- Import gettext only as `_` or by its full name (`gettext`, `gettext_lazy`). `makemessages` can't see aliases like `_l` or `_t`, so their strings silently stay English. A test enforces this. Never put a translatable string inside an f-string.
- Only active language: `uz` (Uzbek, Latin). Code, comments, identifiers and msgids are English. Every msgid must have an Uzbek msgstr. No English may reach the UI (CI checks this).
- The apostrophe in o', g' and the tutuq belgisi is the ASCII `'`. Search must treat `' ‘ ’ ʻ ʼ` as equal.
- Money display: `|som` → `1 250 000 so'm` (narrow no-break space U+202F between groups). Amount inputs format with spaces while typing.
- Mobile first: every screen must work at 360 px width. Lists are cards on phones and tables at `md:` and up. Primary actions are reachable with a thumb.

### Glossary (use these exact Uzbek terms)

| Concept | Uzbek |
|---|---|
| Branch | Filial |
| Student | O'quvchi |
| Group | Guruh |
| Course | Kurs |
| Teacher | O'qituvchi |
| Lead | Lid |
| Trial lesson | Sinov darsi |
| Payment | To'lov |
| Debt | Qarzdorlik (list: Qarzdorlar) |
| Discount | Chegirma |
| Attendance | Davomat (present: Keldi, absent: Kelmadi) |
| Cash desk / cash report | Kassa / Kassa hisoboti; close day: Kunni yopish |
| Charge | Hisoblangan (to'lov) |
| Monthly fee | Oylik to'lov |
| Installments / part | Bo'lib to'lash / To'lov qismi |
| Credit (overpayment) | Avans |
| Balance | Balans |
| Receipt | Chek |
| Reversal | Bekor qilish (storno) |
| Refund | Pul qaytarish |
| Enroll / move / freeze / leave | Guruhga qo'shish / Boshqa guruhga o'tkazish / Muzlatish / Guruhdan chiqish |
| Room | Xona |
| Schedule / lesson | Dars jadvali / Dars |
| Lead stages | Yangi, Bog'lanildi, Sinov darsiga yozildi, Sinov darsiga keldi, O'qishga yozildi, Rad etdi |
| Refusal reason | Rad etish sababi |
| Source | Manba |
| Follow-up task | Vazifa (my tasks: Mening vazifalarim; overdue: Muddati o'tgan) |
| Lead (single) / manager / assignee | Lid / Menejer / Mas'ul |
| Pipeline board | Doska |
| Convert to student | O'quvchiga aylantirish |
| Next follow-up | Keyingi bog'lanish |
| Today's lessons / my groups | Bugungi darslar / Mening guruhlarim |
| Awaiting enrollment | Guruhga qo'shilishi kutilmoqda |
| Over capacity | Sig'imdan oshirish |
| Seats | O'rinlar |
| Import / template | Import / Namuna |
| Studying / left (student status) | O'qiyapti / Ketgan |
| Charges (list) / suggested | Hisoblanganlar / Taklif |
| Recalculate / confirm | Qayta hisoblash / Tasdiqlash |
| Take payment | To'lov qabul qilish |
| Paid / owes / payment expected (manager badge) | To'lagan / Qarzi bor / To'lov kutilmoqda |
| Opening balance | Boshlang'ich qoldiq |
| Additional charge | Qo'shimcha hisob |
| Settings | Sozlamalar |
| Reports / dashboard | Hisobotlar / Bosh sahifa |
| Audit log | Harakatlar jurnali |
| Roles | Direktor, Filial administratori, Sotuv menejeri, O'qituvchi |
| Payment methods | Naqd, Terminal (karta), Bank o'tkazmasi |
| Export to Excel | Excel'ga yuklash |
| Collected (money in, net of reversals and refunds) | Tushum |
| Difference | Farq |
| Conversion (lead → student) | Konversiya |
| Unpaid now / overdue now | Hozir to'lanmagan / Hozir muddati o'tgan |
| Salary / my salary | Maosh / Maoshim |
| Salary sheet | Maosh varaqasi |
| Teacher rate / share | Stavka / O'qituvchi ulushi |
| Bonus / deduction / carry-over | Mukofot / Ushlab qolish / O'tgan oydan qoldiq |
| Correction (salary) | Tuzatish |
| Close the month (salaries) | Oyni yopish |
| Pay out / paid out | Maoshni berish / Berildi |

Add new terms here before using them in the UI.

## Building blocks that already exist (use them, don't re-invent)

- `core.permissions`: `register_permission`, `has_perm`, `require_perm`, `perm_required` (view
  decorator), `scope_by_branch`, `ensure_branch_access` (404), `accessible_branch_ids`.
  `request.branch_filter` is the branch picked in the top-bar switcher (None = all).
- `core.audit.record(...)` / `core.audit.snapshot(obj)`; `core.crud.save_form` / `set_active`
  for audited reference-data writes.
- `core.events.DomainEvent`, `publish`, `subscribe` (+ outbox).
- `core.registry.registry.add_nav(NavItem(...))`, `.add_widget(DashboardWidget(...))`.
- `core.settings_panel.SettingsSection` + `register_section` — a new Sozlamalar page is a
  subclass registered in the module's `ready()`; see `apps/billing/sections.py`.
- `core.system_settings.register_setting(SettingDef(...))` / `get_setting(key)` — typed
  settings that appear automatically in Sozlamalar → Umumiy sozlamalar.
- `core.forms`: `StyledForm`, `StyledModelForm`, `MoneyField`, `PhoneField`, `UzDateField`,
  `UzTimeField` (24-hour text input; never `<input type="time">`, it shows AM/PM).
- `students.services`: `register_enrollment_extension` (billing's hook into enroll / move /
  freeze / unfreeze / leave), `register_profile_panel`, `register_list_badge`,
  `register_import_kind`. Billing uses these in phase 4; don't edit the students module.
- `NavItem.role_priority` orders the phone bottom bar per role.
- `billing.services.monthly.side_lines()`: the one engine that says what a month costs for an
  enrollment (lessons in window minus freezes, minus cancelled lessons, discounts). Joining,
  leaving, freezing, moving and the monthly job all use it. Don't write a second one.
- `billing.services.ledger.create_charge()` / `adjust()`: the only ways to write money rows.
  `billing.services.allocation.rebuild_for_student()` after any change (they do it for you).
- `core.audit_display.register_labels({...})`: Uzbek labels for custom audit keys. A test
  fails if a model field would show up in the audit log without an Uzbek label.
- Template builtins (no `{% load %}` needed): `i18n`, `|som`, `|raqam`, `|sana`, `|sana_vaqt`,
  `|telefon`, `user|can:"perm.code"`, `{% icon "name" %}`, `{% field form.x %}`.
- `billing.domain.rounding.round_amount` — the only money rounding function.
- `core.reports.register_report(ReportDef(...))`: a report with period and branch filters,
  phone cards, desktop table and Excel export for free. See `docs/modules/reports.md`.
- `billing.services.percent_of(amount, basis_points)`: a share of an amount, rounded with the
  one money rounding function. Salaries use it.
- `core.excel.workbook(title, headers, rows, kinds, totals)` / `core.excel.response(...)`:
  every Excel export. Money stays numeric with a so'm number format.
- URLs and slugs are Uzbek (`/sozlamalar/`, `/kirish/`); code identifiers stay English.

## Security and permissions

- Enforce role and branch scope on the server, in services and selectors. Hiding a button is never the protection.
- An object outside the user's scope returns 404.
- Financial fields never reach Sotuv menejeri (only the derived `payment_status`) or O'qituvchi (nothing), with one owner-approved exception: a teacher sees their own salary sheet (students' payments to their groups and their share). See SPEC §13.
- Every new URL must be added to `tests/test_permission_matrix.py` with the expected result for all four roles, in and out of branch. CI fails on unlisted URLs.
- Django admin is dev-only. Never expose it in production.
- Never commit secrets. `.env` is git-ignored, and `.env.example` documents the variables.

## Audit

Call `core.audit.record(actor, action, obj, before, after, branch, reason)` inside the same transaction as the change, for every financial action, settings change, user or role change, and enrollment lifecycle action. Action names are `<module>.<entity>.<verb>`, e.g. `billing.payment.reverse`.

## Tests

- pytest. Pure `domain/` tests need no DB. Integration tests run on real PostgreSQL (never SQLite).
- Required for billing: monthly generation (idempotent), proration, installment schedules, discounts, FIFO allocation, reversals and refunds, the daily-close lock, ledger immutability triggers, receipt numbering under concurrency.
- Use factories (`tests/factories/` or `apps/<m>/tests/factories.py`), not fixtures with hard-coded IDs.
- Tests freeze the clock through `core.dates` helpers (time-machine), always in Asia/Tashkent.

## Migrations and data model

- One migration per logical change, with a readable name. Never edit an applied migration.
- Every money column gets a `CHECK` constraint. Every reference has `on_delete=PROTECT` unless SPEC says otherwise.
- Changes to the approved model in `docs/SPEC.md` §5 need the owner's approval first. Update SPEC in the same commit.

## Git

- Small commits with imperative messages. Each phase ends with a commit, a push, and an updated "Current phase" line above.
- Develop on the session's designated branch. Never force-push shared branches.

## Adding a new module (checklist)

1. Create `apps/<name>/` with the standard layout (`domain/`, `services/`, `selectors.py`, `policies.py`, `events.py`, `handlers.py`, `registry.py`, `views.py`, `urls.py`, `templates/<name>/`, `tests/`).
2. Add it to `INSTALLED_APPS` and its contract to `.importlinter`. Depend only on lower modules' public interfaces.
3. Declare permissions and role defaults in the permission registry. Register nav items, settings sections, dashboard widgets and reports in `AppConfig.ready()`.
4. Integrate through events and registries. Do **not** edit module 1 code to make room for the new module. If an extension point is missing, propose adding one to `core` and get approval.
5. Payment providers (Click, Payme, Uzum): implement `billing.providers.base.PaymentProvider`, register them, add a `billing_payment_method` row with `included_in_cash_close = false`, and verify webhooks before marking a payment `confirmed`.
6. Add Uzbek translations for all new strings, add URLs to the permission matrix, audit all writes, and write tests.
7. Write `docs/modules/<name>.md` (tables, events published and consumed, permissions, settings) and link it from SPEC.
