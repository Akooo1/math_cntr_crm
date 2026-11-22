"""All business dates are computed in Asia/Tashkent. Never call date.today() directly."""

import datetime as dt

from django.utils import timezone

from .datemath import add_months, month_start  # noqa: F401 - re-exported

DATE_FMT = "%d.%m.%Y"
DATETIME_FMT = "%d.%m.%Y %H:%M"


def now() -> dt.datetime:
    return timezone.localtime(timezone.now())


def today() -> dt.date:
    return now().date()


def format_date(value: dt.date | dt.datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        value = timezone.localtime(value) if timezone.is_aware(value) else value
        return value.strftime(DATE_FMT)
    return value.strftime(DATE_FMT)


def format_datetime(value: dt.datetime | None) -> str:
    if value is None:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime(DATETIME_FMT)


def parse_date(raw: str) -> dt.date:
    return dt.datetime.strptime(raw.strip(), DATE_FMT).date()
