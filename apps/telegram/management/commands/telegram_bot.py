"""Long-polling bot process (the `bot` container). Without a token it idles instead of
crashing, so the container doesn't restart in a loop."""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import translation

from apps.telegram.client import TelegramError, get_client
from apps.telegram.services import handle_update

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the Telegram bot (long polling)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One poll, then exit (tests).")

    def handle(self, *args, once=False, **options):
        client = get_client()
        if client is None:
            self.stdout.write("TELEGRAM_BOT_TOKEN is not set: the bot is off.")
            while not once:
                time.sleep(3600)
            return
        try:
            client.call("deleteWebhook", drop_pending_updates=False)
        except TelegramError as exc:
            log.warning("deleteWebhook: %s", exc)
        offset = None
        self.stdout.write("Telegram bot is running.")
        while True:
            try:
                updates = client.call(
                    "getUpdates", timeout=25, offset=offset, allowed_updates=["message"]
                )
            except TelegramError as exc:
                log.warning("getUpdates: %s", exc)
                time.sleep(5)
                updates = []
            for update in updates:
                offset = update["update_id"] + 1
                if not once:  # long-running process: drop stale DB connections
                    close_old_connections()
                try:
                    with translation.override(settings.LANGUAGE_CODE):
                        handle_update(update)
                except Exception:  # one bad update must not stop the bot
                    log.exception("telegram update %s failed", update.get("update_id"))
            if once:
                return
