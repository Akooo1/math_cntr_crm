from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core import phone
from apps.core.roles import Role


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone_number, full_name, role, password=None, **extra):
        user = self.model(
            phone=phone.normalize(phone_number), full_name=full_name, role=role, **extra
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def get_by_natural_key(self, username):
        return self.get(phone=phone.normalize_or_none(username) or username)


class User(AbstractBaseUser):
    """A staff member. One role per user (docs/SPEC.md 5.2). Users are never deleted."""

    phone = models.CharField(_("Phone"), max_length=13, unique=True)
    full_name = models.CharField(_("Full name"), max_length=150)
    role = models.CharField(_("Role"), max_length=20, choices=Role.choices)
    is_active = models.BooleanField(_("Active"), default=True)
    must_change_password = models.BooleanField(_("Must change password"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["full_name", "role"]

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"
        ordering = ["full_name"]
        verbose_name = _("User")
        verbose_name_plural = _("Users")

    def __str__(self):
        return self.full_name

    @property
    def branch_ids(self) -> list[int]:
        """Ids of branches this user works in (rows of accounts_user_branch)."""
        cached = getattr(self, "_branch_ids_cache", None)
        if cached is None:
            cached = list(self.branch_links.values_list("branch_id", flat=True))
            self._branch_ids_cache = cached
        return cached

    def clear_branch_cache(self):
        self.__dict__.pop("_branch_ids_cache", None)

    @property
    def is_director(self) -> bool:
        return self.role == Role.DIRECTOR
