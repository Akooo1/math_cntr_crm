from django.db import migrations

# Starting set; the Direktor edits, adds or switches them off in Sozlamalar.
TEMPLATES = [
    (
        "Darsga kelmadi",
        "Assalomu alaykum! Farzandingiz {oquvchi} bugun ({sana}) {guruh} guruhidagi darsga "
        "kelmadi. Iltimos, sababini {telefon} raqamiga xabar bering. {markaz}",
    ),
    (
        "Darsga kechikdi",
        "Assalomu alaykum! Farzandingiz {oquvchi} bugun ({sana}) {guruh} guruhidagi darsga "
        "kechikib keldi. {markaz}",
    ),
    (
        "Uyga vazifa bajarilmagan",
        "Assalomu alaykum! Farzandingiz {oquvchi} {guruh} guruhida uyga vazifani bajarmagan. "
        "Iltimos, nazorat qiling. {markaz}",
    ),
    (
        "Ota-onalar yig'ilishi",
        "Hurmatli ota-ona! {filial}da ota-onalar yig'ilishi bo'ladi. Batafsil: {telefon}. "
        "{markaz}",
    ),
]


def add(apps, schema_editor):
    Template = apps.get_model("telegram", "Template")
    for i, (title, text) in enumerate(TEMPLATES):
        Template.objects.get_or_create(title=title, defaults={"text": text, "sort_order": (i + 1) * 10})


class Migration(migrations.Migration):
    dependencies = [("telegram", "0002_message_templates")]

    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
