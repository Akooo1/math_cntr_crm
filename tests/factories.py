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


_lead_seq = iter(range(1, 10_000_000))


def make_lead(actor, branch, **data):
    """Create a lead through the service (so stage, history and checks are real)."""
    from apps.crm import services
    from apps.crm.models import LeadSource

    payload = {
        "full_name": data.pop("full_name", "Karimov Aziz"),
        "phone": data.pop("phone", f"+99897{next(_lead_seq):07d}"),
        "source": data.pop("source", None) or LeadSource.objects.first(),
        **data,
    }
    return services.create_lead(actor=actor, branch=branch, data=payload, confirm_duplicate=True)


def make_group(
    actor,
    branch,
    *,
    teacher=None,
    course=None,
    start=None,
    end=None,
    days=(1, 3, 5),
    capacity=10,
    name=None,
):
    """A group with lessons, created through the service (so the calendar is real)."""
    import datetime as dt

    from apps.core.roles import Role
    from apps.students import services
    from apps.students.models import Group

    teacher = teacher or UserFactory(role=Role.TEACHER, branches=[branch])
    if course is None:  # a priced monthly course, so enrolling works with billing active
        from apps.billing.models import Price

        course = CourseFactory()
        Price.objects.create(
            course=course,
            kind=Price.Kind.MONTHLY,
            amount=300_000,
            effective_from=dt.date(2000, 1, 1),
            created_by=actor,
        )
    group = Group(
        branch=branch,
        course=course,
        teacher=teacher,
        name=name or f"G{next(_lead_seq)}",
        start_date=start or dt.date(2026, 9, 1),
        end_date=end,
        capacity=capacity,
    )
    slots = [
        {"weekday": d, "start_time": dt.time(15, 0), "end_time": dt.time(16, 30), "room": None}
        for d in days
    ]
    return services.save_group(actor=actor, group=group, slots=slots)


def make_student(actor, branch, **data):
    from apps.students import services

    payload = {
        "first_name": "Aziz",
        "last_name": "Karimov",
        "parent_phone": f"+99895{next(_lead_seq):07d}",
    }
    payload.update(data)
    return services.create_student(actor=actor, branch=branch, data=payload)
