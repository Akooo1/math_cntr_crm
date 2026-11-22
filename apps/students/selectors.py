from django.db.models import Q

from .models import Student


def find_by_phones(phones: list[str]):
    """Students in any branch with one of these phones (for duplicate warnings).

    Deliberately not branch-scoped: callers decide what to reveal about other branches.
    """
    phones = [p for p in phones if p]
    if not phones:
        return Student.objects.none()
    return Student.objects.filter(
        Q(phone__in=phones) | Q(parent_phone__in=phones) | Q(extra_phone__in=phones)
    ).select_related("branch")
