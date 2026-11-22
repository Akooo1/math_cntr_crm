import time

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, connection


class Command(BaseCommand):
    help = "Wait until PostgreSQL accepts connections (used by the container entrypoint)."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60)

    def handle(self, *args, timeout, **options):
        deadline = time.monotonic() + timeout
        while True:
            try:
                connection.ensure_connection()
                return
            except OperationalError as exc:
                if time.monotonic() > deadline:
                    raise CommandError(f"Database not reachable: {exc}") from exc
                time.sleep(1)
