from django.db import migrations

APPEND_ONLY = ["salaries_staff_pay", "salaries_fixed_line"]


def _append_only(table):
    return migrations.RunSQL(
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION mm_forbid_update_delete();",
        f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};",
    )


class Migration(migrations.Migration):
    dependencies = [("salaries", "0003_staff_pay")]
    operations = [_append_only(t) for t in APPEND_ONLY]
