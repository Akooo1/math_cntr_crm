import factory
from django.contrib.auth import get_user_model

from apps.core.roles import Role
from apps.settings.models import Branch, Course, Room, UserBranch

PASSWORD = "parol12345"


class BranchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Branch
        django_get_or_create = ("receipt_prefix",)

    name = factory.Sequence(lambda n: f"Filial {n}")
    receipt_prefix = factory.Sequence(lambda n: "F" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[n % 26] * 2)
    address = "Toshkent"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()
        skip_postgeneration_save = True

    phone = factory.Sequence(lambda n: f"+99891{n:07d}")
    full_name = factory.Sequence(lambda n: f"Xodim {n}")
    role = Role.BRANCH_ADMIN
    must_change_password = False
    password = factory.PostGenerationMethodCall("set_password", PASSWORD)

    @factory.post_generation
    def branches(self, create, extracted, **kwargs):
        self.save()
        for b in extracted or []:
            UserBranch.objects.create(user=self, branch=b)
        self.clear_branch_cache()


class RoomFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Room

    branch = factory.SubFactory(BranchFactory)
    name = factory.Sequence(lambda n: f"{n}-xona")
    capacity = 12


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Course

    name = factory.Sequence(lambda n: f"Kurs {n}")
    pricing_model = Course.PricingModel.MONTHLY


def page_text(response) -> str:
    """Response body with HTML entities decoded (Django escapes ' as &#x27;)."""
    import html

    return html.unescape(response.content.decode())
