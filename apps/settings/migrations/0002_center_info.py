from django.db import migrations


def add_center(apps, schema_editor):
    CenterInfo = apps.get_model("center_settings", "CenterInfo")
    if not CenterInfo.objects.exists():
        CenterInfo.objects.create(
            center_name="Matematika Markazi", receipt_footer="To'lovingiz uchun rahmat!"
        )


class Migration(migrations.Migration):
    dependencies = [("center_settings", "0001_initial")]

    operations = [migrations.RunPython(add_center, migrations.RunPython.noop)]
