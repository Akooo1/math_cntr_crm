"""Scheduled Telegram jobs (deploy/crontab): `summary` at 09:30, `debts` at 10:00."""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import translation

from apps.telegram import services


class Command(BaseCommand):
    help = "Send the morning summary or the debt reminders."

    def add_arguments(self, parser):
        parser.add_argument("what", choices=["summary", "debts"])

    def handle(self, *args, what, **options):
        with translation.override(settings.LANGUAGE_CODE):
            if what == "summary":
                result = services.send_morning_summary()
            else:
                result = services.send_debt_reminders()
        self.stdout.write(f"telegram {what}: {result}")
