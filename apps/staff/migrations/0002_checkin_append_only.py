from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("staff", "0001_initial"),
        ("core", "0002_append_only_triggers"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE TRIGGER staff_checkin_append_only BEFORE UPDATE OR DELETE ON staff_checkin "
            "FOR EACH ROW EXECUTE FUNCTION mm_forbid_update_delete();",
            "DROP TRIGGER IF EXISTS staff_checkin_append_only ON staff_checkin;",
        ),
    ]
