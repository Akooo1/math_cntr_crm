"""Database-level safety for the store (docs/SPEC.md 17.3, 17.5).

* Prices, sales, sale lines, reversals and stock movements are append-only.
* A paid sale, or the reversal of a paid sale, can't be inserted for a closed cash day.
* Stock on hand is a view over the movements; it is never stored.
"""

from django.db import migrations

APPEND_ONLY = [
    "store_price",
    "store_sale",
    "store_sale_line",
    "store_sale_reversal",
    "store_stock_movement",
]

SQL = (
    "\n".join(
        f"""
CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t}
FOR EACH ROW EXECUTE FUNCTION mm_forbid_update_delete();"""
        for t in APPEND_ONLY
    )
    + """

CREATE OR REPLACE FUNCTION store_sale_closed_day() RETURNS trigger AS $$
BEGIN
    IF NEW.settlement = 'paid' AND EXISTS (
        SELECT 1 FROM billing_cash_day_close c
        WHERE c.branch_id = NEW.branch_id AND c.date = NEW.sold_on) THEN
        RAISE EXCEPTION 'Cash day % is closed for branch %', NEW.sold_on, NEW.branch_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER store_sale_closed_day BEFORE INSERT ON store_sale
FOR EACH ROW EXECUTE FUNCTION store_sale_closed_day();

CREATE OR REPLACE FUNCTION store_reversal_closed_day() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM store_sale s
        JOIN billing_cash_day_close c ON c.branch_id = s.branch_id AND c.date = NEW.reversed_on
        WHERE s.id = NEW.sale_id AND s.settlement = 'paid') THEN
        RAISE EXCEPTION 'Cash day % is closed', NEW.reversed_on
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER store_reversal_closed_day BEFORE INSERT ON store_sale_reversal
FOR EACH ROW EXECUTE FUNCTION store_reversal_closed_day();

CREATE VIEW store_stock_on_hand AS
SELECT MIN(m.id) AS id, m.branch_id, m.product_id, SUM(m.quantity)::bigint AS quantity
FROM store_stock_movement m
GROUP BY m.branch_id, m.product_id;
"""
)

REVERSE = (
    "DROP VIEW IF EXISTS store_stock_on_hand;"
    "DROP TRIGGER IF EXISTS store_reversal_closed_day ON store_sale_reversal;"
    "DROP FUNCTION IF EXISTS store_reversal_closed_day();"
    "DROP TRIGGER IF EXISTS store_sale_closed_day ON store_sale;"
    "DROP FUNCTION IF EXISTS store_sale_closed_day();"
    + "".join(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};" for t in APPEND_ONLY)
)


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0001_initial"),
        ("core", "0002_append_only_triggers"),
        ("billing", "0005_ledger_guards_and_views"),
    ]

    operations = [migrations.RunSQL(SQL, REVERSE)]
