"""Template helpers available in every template (registered as a builtin)."""

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

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
    try:
        return mapping.get(key)
    except AttributeError:
        return None


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
