# Telegram module (`apps/telegram`): bot, debt reminders, morning summary

Rules: docs/SPEC.md §15. Sits with `reports` and `salaries` (reads billing, staff,
students, settings). Bot API via the standard library (`client.py`); no extra package.

## Tables
`telegram_chat` (connections), `telegram_message` (every message sent, also used to avoid
repeats).

## Processes
| What | Where | When |
|---|---|---|
| Polling bot: /start, phone sharing, /stop, staff links | container `bot`: `manage.py telegram_bot` | always |
| Morning summary to the Direktor | cron: `manage.py telegram_send summary` | 09:30 |
| Debt reminders to parents | cron: `manage.py telegram_send debts` | 10:00 |

Without `TELEGRAM_BOT_TOKEN` the bot container idles and nothing is sent.

## Connecting
- Parents: /start → "Telefon raqamni yuborish" button. Only the person's own number is
  accepted (`contact.user_id == from.id`); it's matched against students' parent, own and
  extra phones (`students.selectors.find_by_phones`).
- Direktor: Sozlamalar → Telegram → "Telegramimni ulash": `t.me/<bot>?start=<user>_<hmac>`,
  valid today and tomorrow (`services.linking.link_token`).

## Permissions
| Code | Roles |
|---|---|
| `telegram.manage` | Direktor |
| `telegram.view` | Direktor, Filial administratori (student profile badge) |

## Settings
`telegram.debt_reminders` (0 = off), `telegram.debt_min_days` (3),
`telegram.debt_repeat_days` (7, counted in calendar days).

## Events
Consumes none (jobs read billing and staff directly). Publishes none.

## Testing without Telegram
`client.set_client(fake)` installs a fake; see `apps/telegram/tests/test_bot.py`.
