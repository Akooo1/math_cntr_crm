"""Minimal Telegram Bot API client (https://core.telegram.org/bots/api). Standard library
only. Tests replace `get_client()` with a fake."""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger(__name__)


class TelegramError(Exception):
    def __init__(self, description: str, code: int | None = None):
        super().__init__(description)
        self.description = description
        self.code = code

    @property
    def chat_gone(self) -> bool:
        """The user blocked the bot or deleted the chat: stop writing to it."""
        return self.code in (400, 403) and any(
            w in self.description.lower() for w in ("blocked", "deactivated", "chat not found")
        )


class TelegramClient:
    def __init__(self, token: str, timeout: int = 35):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.timeout = timeout

    def call(self, method: str, **params):
        req = urllib.request.Request(
            self.base + method,
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read())
            except ValueError:
                raise TelegramError(str(exc), exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TelegramError(str(exc)) from None
        if not body.get("ok"):
            raise TelegramError(body.get("description", "error"), body.get("error_code"))
        return body["result"]

    def send(self, chat_id: int, text: str, **extra):
        return self.call("sendMessage", chat_id=chat_id, text=text, **extra)


def token() -> str:
    return getattr(settings, "TELEGRAM_BOT_TOKEN", "") or ""


_client = None


def get_client() -> TelegramClient | None:
    """None when no token is configured: the bot is off."""
    global _client
    if not token():
        return None
    if _client is None:
        _client = TelegramClient(token())
    return _client


def set_client(client) -> None:
    """Tests: install a fake client (or None)."""
    global _client
    _client = client
