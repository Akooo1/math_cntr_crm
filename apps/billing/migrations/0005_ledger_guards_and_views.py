"""Database-level money safety (docs/SPEC.md 4.7, 6.4.9).

* Ledger tables are append-only (UPDATE/DELETE raise). The one exception is the future online
  payment flow: a payment may change status from 'pending' to 'confirmed' and nothing else.
* No payment, reversal or refund can be inserted for a branch-day that is closed, when its
  method is counted in the daily cash report.
* Views for the derived numbers: charge net/paid and the student balance.
"""

from django.db import migrations

APPEND_ONLY = [
    "billing_charge",
    "billing_charge_discount",
    "billing_charge_adjustment",
    "billing_cash_day_close",
]

SQL = (
    "\n".join(
        f"""
CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t}
FOR EACH ROW EXECUTE FUNCTION mm_forbid_update_delete();"""
        for t in APPEND_ONLY
    )
    + """

CREATE OR REPLACE FUNCTION billing_payment_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.status = 'pending' AND NEW.status = 'confirmed'
       AND (to_jsonb(NEW) - 'status') = (to_jsonb(OLD) - 'status') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Table billing_payment is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER billing_payment_append_only BEFORE UPDATE OR DELETE ON billing_payment
FOR EACH ROW EXECUTE FUNCTION billing_payment_guard();

CREATE OR REPLACE FUNCTION billing_payment_closed_day() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM billing_cash_day_close c
               WHERE c.branch_id = NEW.branch_id AND c.date = NEW.paid_on)
       AND (SELECT m.included_in_cash_close FROM billing_payment_method m
            WHERE m.id = NEW.method_id) THEN
        RAISE EXCEPTION 'Cash day % is closed for branch %', NEW.paid_on, NEW.branch_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER billing_payment_closed_day BEFORE INSERT ON billing_payment
FOR EACH ROW EXECUTE FUNCTION billing_payment_closed_day();

CREATE VIEW billing_charge_net AS
SELECT c.id AS charge_id, c.student_id, c.branch_id, c.group_id, c.course_id,
       c.enrollment_id, c.kind, c.due_date, c.period_month,
       (c.amount
         - COALESCE((SELECT SUM(d.amount) FROM billing_charge_discount d WHERE d.charge_id = c.id), 0)
         + COALESCE((SELECT SUM(a.amount) FROM billing_charge_adjustment a WHERE a.charge_id = c.id), 0)
       )::bigint AS net,
       COALESCE((SELECT SUM(al.amount) FROM billing_allocation al WHERE al.charge_id = c.id), 0)::bigint
         AS paid
FROM billing_charge c;

CREATE VIEW billing_student_balance AS
SELECT s.id AS student_id, p.paid, n.charged, p.paid - n.charged AS balance
FROM students_student s
CROSS JOIN LATERAL (
    SELECT COALESCE(SUM(CASE WHEN x.kind = 'payment' THEN x.amount ELSE -x.amount END), 0)::bigint
        AS paid
    FROM billing_payment x WHERE x.student_id = s.id AND x.status = 'confirmed'
) p
CROSS JOIN LATERAL (
    SELECT COALESCE(SUM(v.net), 0)::bigint AS charged
    FROM billing_charge_net v WHERE v.student_id = s.id
) n;
"""
)

REVERSE = (
    "DROP VIEW IF EXISTS billing_student_balance; DROP VIEW IF EXISTS billing_charge_net;"
    "DROP TRIGGER IF EXISTS billing_payment_closed_day ON billing_payment;"
    "DROP FUNCTION IF EXISTS billing_payment_closed_day();"
    "DROP TRIGGER IF EXISTS billing_payment_append_only ON billing_payment;"
    "DROP FUNCTION IF EXISTS billing_payment_guard();"
    + "".join(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};" for t in APPEND_ONLY)
)


class Migration(migrations.Migration):
    dependencies = [("billing", "0004_ledger")]

    operations = [migrations.RunSQL(SQL, REVERSE)]
