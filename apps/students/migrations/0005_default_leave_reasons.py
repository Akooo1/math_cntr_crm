"""Starting list of leave reasons (editable in Sozlamalar -> Ketish sabablari)."""

from django.db import migrations

REASONS = [
    "Narxi qimmat",
    "Dars vaqti to'g'ri kelmadi",
    "O'qituvchi yoqmadi",
    "Natija bo'lmadi",
    "Boshqa joyga ko'chib ketdi",
    "Boshqa markazga o'tdi",
    "Kursni tugatdi",
    "Boshqa sabab",
]


def add(apps, schema_editor):
    LeaveReason = apps.get_model("students", "LeaveReason")
    for i, name in enumerate(REASONS, start=1):
        LeaveReason.objects.get_or_create(name=name, defaults={"sort_order": i * 10})


class Migration(migrations.Migration):
    dependencies = [("students", "0004_leave_reasons")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
