from django.conf import settings as dj_settings
from django.urls import reverse

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


def layout(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"center_name": _center_name()}
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
    mobile = sorted(nav, key=lambda n: n["item"].mobile_priority)
    return {
        "center_name": _center_name(),
        "nav": nav,
        "nav_mobile": mobile[:4],
        "nav_mobile_more": mobile[4:],
        "branch_options": _branch_options(request),
    }
