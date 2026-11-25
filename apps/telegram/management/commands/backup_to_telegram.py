"""Back up the database and send it to the Direktor's Telegram.

    python manage.py backup_to_telegram                    # now, by hand
    python manage.py backup_to_telegram --nightly-if-configured  # deploy/crontab
    python manage.py backup_to_telegram --before-migrate   # start of every deploy

--before-migrate only backs up when the update changes the database, and exits with an error
when the backup fails, so scripts/entrypoint.sh stops before migrating.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import translation

from apps.telegram.services import backup


class Command(BaseCommand):
    help = "Back up the database and send it to the Direktor's Telegram."

    def add_arguments(self, parser):
        parser.add_argument("--before-migrate", action="store_true")
        parser.add_argument(
            "--nightly-if-configured",
            action="store_true",
            help="Nightly job: skip quietly while no bot token or no Direktor chat is set up.",
        )

    def handle(self, *args, before_migrate=False, nightly_if_configured=False, **options):
        reason = "nightly"
        if nightly_if_configured and not backup.configured():
            self.stdout.write(
                "backup: Telegram isn't set up yet (token or Direktor chat), skipped."
            )
            return
        if before_migrate:
            set_up, changes = backup.pending_migrations()
            if not set_up:
                self.stdout.write("backup: new empty database, nothing to back up.")
                return
            if not changes:
                self.stdout.write("backup: this update has no database changes, none needed.")
                return
            reason = "update"
        try:
            with translation.override(settings.LANGUAGE_CODE):
                result = backup.send_backup(reason=reason)
        except backup.BackupError as exc:
            raise CommandError(f"backup FAILED: {exc}") from None
        self.stdout.write(
            f"backup: {result['filename']} ({result['bytes']} bytes) sent to "
            f"{result['delivered']} Direktor chat(s)."
        )
