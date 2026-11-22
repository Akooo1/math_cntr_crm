"""Login throttling backed by Django's cache (database cache in production)."""

from django.core.cache import cache

WINDOW_SECONDS = 15 * 60
MAX_PER_PHONE = 10
MAX_PER_IP = 30


def _keys(phone: str, ip: str | None):
    return f"login:phone:{phone}", f"login:ip:{ip or '-'}"


def is_blocked(phone: str, ip: str | None) -> bool:
    phone_key, ip_key = _keys(phone, ip)
    return cache.get(phone_key, 0) >= MAX_PER_PHONE or cache.get(ip_key, 0) >= MAX_PER_IP


def register_failure(phone: str, ip: str | None) -> None:
    for key in _keys(phone, ip):
        if cache.add(key, 1, WINDOW_SECONDS):
            continue
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, WINDOW_SECONDS)


def reset(phone: str) -> None:
    cache.delete(_keys(phone, None)[0])
