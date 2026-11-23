"""Diagnose the Telegram setup: token, connection to Telegram, webhook, connected chats.

docker compose exec bot python manage.py telegram_check
"""

from django.core.management.base import BaseCommand

from apps.core.system_settings import get_setting
from apps.telegram.client import TelegramError, get_client, token
from apps.telegram.models import Chat, Message


class Command(BaseCommand):
    help = "Check the Telegram bot configuration step by step."

    def ok(self, text):
        self.stdout.write(self.style.SUCCESS(f"OK    {text}"))

    def bad(self, text):
        self.stdout.write(self.style.ERROR(f"FAIL  {text}"))

    def handle(self, *args, **options):
        t = token()
        if not t:
            self.bad(
                "TELEGRAM_BOT_TOKEN is empty in this container. Put it into .env next to "
                "docker-compose.yml (or into Railway variables) and recreate the containers."
            )
            return
        shown = f"{t[:6]}…{t[-4:]}" if len(t) > 12 else "(too short)"
        if ":" not in t or t != t.strip() or t.startswith(("'", '"')):
            self.bad(f"token {shown} looks malformed: no quotes or spaces, format 123456:ABC...")
        else:
            self.ok(f"token is set ({shown})")
        client = get_client()
        try:
            me = client.call("getMe")
        except TelegramError as exc:
            if exc.code == 401:
                self.bad("Telegram rejects the token (401). Copy it again from @BotFather.")
            else:
                self.bad(f"can't reach api.telegram.org: {exc}")
            return
        self.ok(f"Telegram knows the bot: @{me.get('username')}")
        try:
            hook = client.call("getWebhookInfo")
        except TelegramError as exc:
            self.bad(f"getWebhookInfo: {exc}")
        else:
            if hook.get("url"):
                self.bad(
                    f"a webhook is set ({hook['url']}): the bot container removes it on start; "
                    "restart the bot container."
                )
            else:
                self.ok(f"no webhook; waiting updates: {hook.get('pending_update_count', 0)}")
        parents = Chat.objects.filter(kind="parent", is_active=True).count()
        staff = Chat.objects.filter(kind="staff", is_active=True).count()
        self.ok(f"connected chats: {parents} parents, {staff} staff")
        last = Message.objects.first()
        if last:
            self.stdout.write(
                f"      last message: {last.get_kind_display()} {last.status} "
                f"{last.error[:80]}".rstrip()
            )
        if not get_setting("telegram.debt_reminders"):
            self.stdout.write("      note: debt reminders are OFF (Sozlamalar → Umumiy).")
