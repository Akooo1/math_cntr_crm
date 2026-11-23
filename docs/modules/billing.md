# Billing module (`apps/billing`) — To'lovlar, Qarzdorlar, Kassa

## Tables
Configuration: `billing_price` (immutable history), `billing_installment_template(_part)`,
`billing_discount_type`, `billing_payment_method`.
Assignments: `billing_discount_assignment`, `billing_installment_plan`, `..._plan_revision`.
Ledger (append-only, triggers): `billing_charge`, `billing_charge_discount`,
`billing_charge_adjustment`, `billing_payment`, `billing_cash_day_close`.
Derived: `billing_allocation` (FIFO cache), views `billing_charge_net`, `billing_student_balance`.
`billing_receipt_counter` holds the per-branch receipt sequence.

## Money rules in code
| Rule | Where |
|---|---|
| Rounding to the step | `domain/rounding.py` |
| Proration by lessons | `domain/proration.py`, `services/monthly.py` |
| Discount lines (percents, then fixed; never below 0) | `domain/discounts.py` |
| Installment split and due dates | `domain/installments.py`, `services/installments.py` |
| FIFO allocation, refund from newest money | `domain/allocation.py`, `services/allocation.py` |
| Enroll / move / freeze / unfreeze / leave money | `enrollment.py` (students extension) |
| Payments, receipts, reversal, refund | `services/payments.py` |
| Daily cash close | `services/cash.py` + DB trigger |
| Direktor corrections | `services/corrections.py` |

## Permissions
| Code | Roles |
|---|---|
| `billing.view`, `billing.payment.create`, `billing.discount.assign`, `billing.plan.edit`, `billing.cash.view`, `billing.cash.close`, `billing.debtors.view` | Direktor, Filial administratori |
| `billing.reverse` (reversal, refund, correction, extra charge), `billing.discount.custom` | Direktor |
| `billing.payment_status.view` (badge only, no amounts) | Direktor, Filial administratori, Sotuv menejeri |

## Events (outbox)
`billing.payment_recorded` (the future Telegram bot can send the receipt to parents),
`billing.payment_reversed`, `billing.refund_issued`.

## Jobs
`generate_monthly_charges [--month YYYY-MM]`, daily and idempotent.

## Adding an online provider (Click, Payme, Uzum)
Implement `providers.base.PaymentProvider`, register it with `providers.register_provider`,
add a payment method with `included_in_cash_close = false`, create payments with
`status="pending"`, and set `confirmed` only after webhook verification. The database
allows exactly that one update. The allocation, receipts and reports need no change.
