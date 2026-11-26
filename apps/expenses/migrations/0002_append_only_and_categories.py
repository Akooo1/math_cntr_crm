from django.db import migrations

CATEGORIES = ["Ijara", "Kommunal to'lovlar", "Reklama", "Kanselyariya", "Xo'jalik", "Boshqa"]


def add_categories(apps, schema_editor):
    Category = apps.get_model("expenses", "Category")
    for i, name in enumerate(CATEGORIES, start=1):
        Category.objects.get_or_create(name=name, defaults={"sort_order": i * 10})


class Migration(migrations.Migration):
    dependencies = [("expenses", "0001_initial"), ("core", "0002_append_only_triggers")]
    operations = [
        migrations.RunSQL(
            "CREATE TRIGGER expenses_expense_append_only BEFORE UPDATE OR DELETE ON "
            "expenses_expense FOR EACH ROW EXECUTE FUNCTION mm_forbid_update_delete();",
            "DROP TRIGGER IF EXISTS expenses_expense_append_only ON expenses_expense;",
        ),
        migrations.RunPython(add_categories, migrations.RunPython.noop),
    ]
