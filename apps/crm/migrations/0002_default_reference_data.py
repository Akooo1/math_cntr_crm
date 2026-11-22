from django.db import migrations

STAGES = [
    # name, kind, color, order
    ("Yangi", "new", "sky", 10),
    ("Bog'lanildi", "contacted", "slate", 20),
    ("Sinov darsiga yozildi", "trial_booked", "violet", 30),
    ("Sinov darsiga keldi", "trial_attended", "amber", 40),
    ("O'qishga yozildi", "won", "emerald", 90),
    ("Rad etdi", "lost", "rose", 100),
]
SOURCES = ["Instagram", "Telegram", "Telefon qo'ng'irog'i", "O'zi kelgan", "Tavsiya"]
REASONS = [
    "Narx qimmat",
    "Vaqt to'g'ri kelmadi",
    "Boshqa markazni tanladi",
    "Javob bermadi",
    "Uzoq masofa",
]


def add_defaults(apps, schema_editor):
    LeadStage = apps.get_model("crm", "LeadStage")
    LeadSource = apps.get_model("crm", "LeadSource")
    RefusalReason = apps.get_model("crm", "RefusalReason")
    for name, kind, color, order in STAGES:
        LeadStage.objects.get_or_create(
            kind=kind, defaults={"name": name, "color": color, "sort_order": order}
        )
    for i, name in enumerate(SOURCES):
        LeadSource.objects.get_or_create(name=name, defaults={"sort_order": (i + 1) * 10})
    for i, name in enumerate(REASONS):
        RefusalReason.objects.get_or_create(name=name, defaults={"sort_order": (i + 1) * 10})


class Migration(migrations.Migration):
    dependencies = [("crm", "0001_initial")]

    operations = [migrations.RunPython(add_defaults, migrations.RunPython.noop)]
