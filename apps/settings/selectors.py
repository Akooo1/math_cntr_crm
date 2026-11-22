from django.conf import settings as dj_settings

from apps.core.permissions import scope_by_branch

from .models import Branch, CenterInfo, Room


def center_info() -> CenterInfo:
    info = CenterInfo.objects.first()
    if info is None:
        info = CenterInfo(center_name=dj_settings.CENTER_NAME_DEFAULT)
    return info


def center_name() -> str:
    return center_info().center_name


def branches_for_switcher(ids: set[int] | None) -> list[Branch]:
    qs = Branch.objects.filter(is_active=True)
    if ids is not None:
        qs = qs.filter(id__in=ids)
    return list(qs.order_by("name"))


def branches_for(user):
    return scope_by_branch(Branch.objects.all(), user, field="id")


def rooms_for(user):
    return scope_by_branch(Room.objects.select_related("branch"), user)


def receipt_details(branch: Branch) -> dict:
    """Center details merged with the branch override, for receipts."""
    info = center_info()
    override = getattr(branch, "receipt_info", None) if branch.pk else None
    pick = lambda attr, fallback: (getattr(override, attr, "") if override else "") or fallback  # noqa: E731
    return {
        "center_name": info.center_name,
        "legal_name": pick("legal_name", info.legal_name),
        "inn": pick("inn", info.inn),
        "address": pick("address", branch.address),
        "phone": pick("phone", branch.phone or info.phone),
        "footer": pick("footer", info.receipt_footer),
        "bank_details": info.bank_details,
        "branch_name": branch.name,
    }
