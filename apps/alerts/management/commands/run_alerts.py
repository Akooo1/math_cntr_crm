"""Every 15 minutes (deploy/crontab): make warning tasks and close the ones that resolved."""

from django.core.management.base import BaseCommand

from apps.alerts.services import run_checks


class Command(BaseCommand):
    help = "Check missed lessons, overdue debts and uncontacted leads; make warning tasks."

    def handle(self, *args, **options):
        made = run_checks()
        self.stdout.write(
            "warnings made: missed lessons {absence}, debts {debt}, leads {lead}".format(**made)
        )
