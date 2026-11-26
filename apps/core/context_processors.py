from django.conf import settings as dj_settings
from django.urls import reverse
from django.utils.dates import MONTHS
from django.utils.translation import gettext as _

from . import dates
from .permissions import accessible_branch_ids, has_perm
from .registry import registry


def _center_name() -> str:
    provider = registry.center_name_provider
    if provider is None:
        return dj_settings.CENTER_NAME_DEFAULT
    try:
        return provider() or dj_settings.CENTER_NAME_DEFAULT
    except Exception:  # noqa: BLE001 - the layout must render even before migrations
        return dj_settings.CENTER_NAME_DEFAULT


def _branch_options(request):
    provider = registry.branch_options_provider
    if provider is None:
        return None
    branches = provider(accessible_branch_ids(request.user))
    if len(branches) <= 1:
        return None
    return {"branches": branches, "current": getattr(request, "branch_filter", None)}


def weekday_names() -> list[str]:
    """Monday first, like dt.date.weekday()."""
    return [
        _("Monday"),
        _("Tuesday"),
        _("Wednesday"),
        _("Thursday"),
        _("Friday"),
        _("Saturday"),
        _("Sunday"),
    ]


def ui_strings() -> dict:
    """Translated strings for static/js/app.js, rendered with json_script in base.html."""
    return {
        "days": weekday_names(),
        "days_short": [
            _("Mon"),
            _("Tue"),
            _("Wed"),
            _("Thu"),
            _("Fri"),
            _("Sat"),
            _("Sun"),
        ],
        "months": [str(MONTHS[i]) for i in range(1, 13)],
        "today": _("Today"),
        "close": _("Close"),
        "calendar": _("Calendar"),
        "choose_date": _("Choose a date"),
        "prev_month": _("Previous month"),
        "next_month": _("Next month"),
        "saving": _("Saving…"),
        "undo": _("Undo"),
        # %s: the stage's name
        "moved_to": _("Moved to: %s"),
    }


def clock() -> dict:
    """The top bar's "Seshanba, 25.11.2026 · 14:32" (Asia/Tashkent). JS keeps it current."""
    now = dates.now()
    return {
        "iso": now.strftime("%Y-%m-%dT%H:%M"),
        "weekday": weekday_names()[now.weekday()],
        "rest": f"{dates.format_date(now)} · {now:%H:%M}",
    }


def _asset_version() -> str:
    """Development only: changes whenever app.css or app.js changes, so the browser never
    keeps an old stylesheet. Production URLs are already hashed by the manifest storage."""
    from django.conf import settings

    if not settings.DEBUG:
        return ""
    stamps = []
    for rel in ("static/dist/app.css", "static/js/app.js"):
        try:
            stamps.append(str(int((settings.BASE_DIR / rel).stat().st_mtime)))
        except OSError:
            stamps.append("0")
    return "-".join(stamps)


def layout(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"center_name": _center_name(), "ui_i18n": ui_strings(), "asset_v": _asset_version()}
    items = sorted(
        (i for i in registry.nav.values() if has_perm(user, i.permission)),
        key=lambda i: i.order,
    )
    nav = []
    for item in items:
        url = reverse(item.url_name)
        prefix = item.active_prefix or url
        active = request.path == "/" if prefix == "/" else request.path.startswith(prefix)
        nav.append({"item": item, "url": url, "active": active})
    mobile = sorted(nav, key=lambda n: n["item"].priority_for(user.role))
    return {
        "center_name": _center_name(),
        "nav": nav,
        "nav_mobile": mobile[:4],
        "nav_mobile_more": mobile[4:],
        "branch_options": _branch_options(request),
        "clock": clock(),
        "ui_i18n": ui_strings(),
        "asset_v": _asset_version(),
    }
