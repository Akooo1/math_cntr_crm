import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from apps.billing.services.monthly import generate_monthly_charges


class Command(BaseCommand):
    help = "Create this month's charges (idempotent; cron runs it daily). --month 2026-12"

    def add_arguments(self, parser):
        parser.add_argument("--month", help="YYYY-MM (default: the current month in Tashkent)")

    def handle(self, *args, month=None, **options):
        target = None
        if month:
            try:
                target = dt.datetime.strptime(month, "%Y-%m").date()
            except ValueError as exc:
                raise CommandError("Use --month YYYY-MM") from exc
        summary = generate_monthly_charges(target)
        self.stdout.write(
            f"{summary['month']}: created {summary['created']}, without price {summary['no_price']}"
        )
