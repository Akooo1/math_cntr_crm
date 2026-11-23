from django.db import migrations

APPEND_ONLY = ["salaries_rate", "salaries_month", "salaries_line", "salaries_payout"]

ADJUSTMENT_GUARD = """
CREATE OR REPLACE FUNCTION salaries_adjustment_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'salaries_adjustment rows are not edited; delete and re-add'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF EXISTS (SELECT 1 FROM salaries_month WHERE month = OLD.month) THEN
        RAISE EXCEPTION 'salary month % is closed', OLD.month
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER salaries_adjustment_locked
BEFORE UPDATE OR DELETE ON salaries_adjustment
FOR EACH ROW EXECUTE FUNCTION salaries_adjustment_guard();
"""

# A new bonus or deduction can't be added to a closed month either.
ADJUSTMENT_INSERT_GUARD = """
CREATE OR REPLACE FUNCTION salaries_adjustment_insert_guard() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM salaries_month WHERE month = NEW.month) THEN
        RAISE EXCEPTION 'salary month % is closed', NEW.month
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER salaries_adjustment_closed_month
BEFORE INSERT ON salaries_adjustment
FOR EACH ROW EXECUTE FUNCTION salaries_adjustment_insert_guard();
"""


def _append_only(table):
    return migrations.RunSQL(
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION mm_forbid_update_delete();",
        f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("salaries", "0001_initial"),
        ("core", "0002_append_only_triggers"),
    ]

    operations = [
        *[_append_only(t) for t in APPEND_ONLY],
        migrations.RunSQL(
            ADJUSTMENT_GUARD,
            "DROP TRIGGER IF EXISTS salaries_adjustment_locked ON salaries_adjustment; "
            "DROP FUNCTION IF EXISTS salaries_adjustment_guard();",
        ),
        migrations.RunSQL(
            ADJUSTMENT_INSERT_GUARD,
            "DROP TRIGGER IF EXISTS salaries_adjustment_closed_month ON salaries_adjustment; "
            "DROP FUNCTION IF EXISTS salaries_adjustment_insert_guard();",
        ),
    ]
