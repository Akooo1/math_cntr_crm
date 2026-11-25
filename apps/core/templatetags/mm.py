"""Template helpers available in every template (registered as a builtin)."""

import datetime as dt

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from .. import dates, money, phone
from ..icons import ICONS
from ..permissions import has_perm

register = template.Library()


@register.filter
def som(value):
    """1250000 -> 1 250 000 so'm"""
    if value in (None, ""):
        return ""
    return money.format_som(int(value))


@register.filter
def raqam(value):
    """1250000 -> 1 250 000 (no currency)"""
    if value in (None, ""):
        return ""
    return money.group_digits(int(value))


@register.filter
def sana(value):
    return dates.format_date(value)


@register.filter
def sana_vaqt(value):
    return dates.format_datetime(value)


@register.filter
def telefon(value):
    return phone.format_phone(value)


@register.filter
def can(user, code):
    return has_perm(user, code)


@register.filter
def get_item(mapping, key):
    """dict lookup, or index for lists/tuples."""
    try:
        if isinstance(mapping, list | tuple):
            return mapping[int(key)]
        return mapping.get(key)
    except (AttributeError, IndexError, ValueError, TypeError):
        return None


@register.filter
def foiz(value):
    """0.425 -> 42,5%"""
    if value in (None, ""):
        return ""
    pct = round(float(value) * 100, 1)
    text = f"{pct:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{text}%"


@register.filter
def change_pct(now, before):
    """Relative change as a signed percent string, or '' when there is no base."""
    if not before:
        return ""
    pct = round((now - before) * 100 / before)
    return f"{'+' if pct > 0 else ''}{pct}%"


@register.simple_tag
def icon(name, css="w-5 h-5"):
    body = ICONS.get(name, ICONS["dots"])
    return format_html(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        'stroke-linejoin="round" class="{}" aria-hidden="true">{}</svg>',
        css,
        mark_safe(body),  # noqa: S308 - static markup from ICONS
    )


@register.inclusion_tag("components/field.html")
def field(bound_field, hint=""):
    return {"f": bound_field, "hint": hint or bound_field.help_text}


@register.simple_tag
def column_value(column, obj):
    return column.value(obj)


def relative_label(value: dt.datetime, now: dt.datetime | None = None) -> str:
    """'hozirgina', '5 daqiqa oldin', '2 soat oldin', 'kecha 14:30', '3 kun oldin', 'in 2 hours'
    for the future, and the plain date after a week."""
    now = now or dates.now()
    value = timezone.localtime(value) if timezone.is_aware(value) else value
    seconds = int((now - value).total_seconds())
    future = seconds < 0
    seconds = abs(seconds)
    if seconds < 60:
        return _("just now")
    minutes, hours = seconds // 60, seconds // 3600
    days = (now.date() - value.date()).days
    if future:
        if minutes < 60:
            return ngettext("in %(n)s minute", "in %(n)s minutes", minutes) % {"n": minutes}
        if hours < 24:
            return ngettext("in %(n)s hour", "in %(n)s hours", hours) % {"n": hours}
        return dates.format_datetime(value)
    if minutes < 60:
        return ngettext("%(n)s minute ago", "%(n)s minutes ago", minutes) % {"n": minutes}
    if days == 0:
        return ngettext("%(n)s hour ago", "%(n)s hours ago", hours) % {"n": hours}
    if days == 1:
        return _("yesterday %(time)s") % {"time": value.strftime("%H:%M")}
    if days < 7:
        return ngettext("%(n)s day ago", "%(n)s days ago", days) % {"n": days}
    return dates.format_date(value)


@register.simple_tag
def relative_time(value):
    """<time> with a relative label ("2 soat oldin") and the exact time on hover."""
    if not value:
        return ""
    if not isinstance(value, dt.datetime):
        return dates.format_date(value)
    exact = dates.format_datetime(value)
    local = timezone.localtime(value) if timezone.is_aware(value) else value
    return format_html(
        '<time datetime="{}" title="{}">{}</time>',
        local.isoformat(timespec="minutes"),
        exact,
        relative_label(value),
    )
