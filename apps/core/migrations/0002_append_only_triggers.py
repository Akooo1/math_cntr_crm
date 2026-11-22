from django.db import migrations

# Generic guard used by every append-only table (audit log, price history, ledger).
FUNCTION = """
CREATE OR REPLACE FUNCTION mm_forbid_update_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Table % is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

AUDIT_TRIGGER = """
CREATE TRIGGER core_audit_log_append_only
BEFORE UPDATE OR DELETE ON core_audit_log
FOR EACH ROW EXECUTE FUNCTION mm_forbid_update_delete();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.RunSQL(FUNCTION, "DROP FUNCTION IF EXISTS mm_forbid_update_delete() CASCADE;"),
        migrations.RunSQL(
            AUDIT_TRIGGER, "DROP TRIGGER IF EXISTS core_audit_log_append_only ON core_audit_log;"
        ),
    ]
