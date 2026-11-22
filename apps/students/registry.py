from django.utils.translation import gettext_lazy as _

from apps.core.permissions import register_permission
from apps.core.roles import Role

# Sotuv menejeri creates students only by converting a lead (docs/SPEC.md 6.2).
register_permission(
    "students.create",
    _("Create students"),
    {Role.DIRECTOR, Role.BRANCH_ADMIN, Role.SALES_MANAGER},
)
