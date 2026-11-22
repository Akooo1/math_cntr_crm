from django.db import migrations

TRIGGER = """
CREATE TRIGGER billing_price_append_only
BEFORE UPDATE OR DELETE ON billing_price
FOR EACH ROW EXECUTE FUNCTION mm_forbid_update_delete();
"""

METHODS = [
    # name, provider_code, included_in_cash_close, sort_order
    ("Naqd", "manual", True, 10),
    ("Terminal (karta)", "manual", True, 20),
    ("Bank o'tkazmasi", "manual", True, 30),
    ("Boshlang'ich qoldiq", "opening_balance", False, 900),
]


def add_methods(apps, schema_editor):
    PaymentMethod = apps.get_model("billing", "PaymentMethod")
    for name, code, cash, order in METHODS:
        PaymentMethod.objects.get_or_create(
            name=name,
            defaults={"provider_code": code, "included_in_cash_close": cash, "sort_order": order},
        )


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial"), ("core", "0002_append_only_triggers")]

    operations = [
        migrations.RunSQL(TRIGGER, "DROP TRIGGER IF EXISTS billing_price_append_only ON billing_price;"),
        migrations.RunPython(add_methods, migrations.RunPython.noop),
    ]
