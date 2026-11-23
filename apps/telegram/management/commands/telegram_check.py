"""Diagnose the Telegram setup: token, connection to Telegram, webhook, connected chats.

docker compose exec bot python manage.py telegram_check
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.system_settings import get_setting
from apps.telegram.client import TelegramError, get_client, token
from apps.telegram.models import Chat, Message

ENV_NAMES = (".env", ".env.txt", "env", "env.txt", ".env.example", ".env.local")


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
            self._explain_env_files()
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

    def _explain_env_files(self):
        """What the project folder (mounted at /app locally) contains, without values."""
        from config import dotenv

        base = settings.BASE_DIR
        found = [n for n in ENV_NAMES if (base / n).is_file()]
        if not found:
            self.stdout.write(f"      no .env file in {base} (the folder with docker-compose.yml)")
            return
        for name in found:
            values = dotenv.parse((base / name).read_text(encoding="utf-8", errors="replace"))
            has = "TELEGRAM_BOT_TOKEN" in values
            filled = bool(values.get("TELEGRAM_BOT_TOKEN"))
            state = (
                "has the token" if filled else ("token line is empty" if has else "no token line")
            )
            self.stdout.write(f"      {name}: {state}")
        if ".env" not in found:
            self.stdout.write(
                "      the file must be named exactly .env (Windows may have saved .env.txt)"
            )
