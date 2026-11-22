"""Demo data. Phase 1 content: branches, staff for every role, rooms, courses, prices,
installment templates and discount types. Later phases extend this command.

Safe to run twice: it does nothing when demo users already exist.
"""

import datetime as dt

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.billing.models import DiscountType, InstallmentTemplate, InstallmentTemplatePart, Price
from apps.core import dates
from apps.core.roles import Role
from apps.settings.models import Branch, Course, Room, UserBranch

DEMO_PASSWORD = "demo12345"

USERS = [
    # phone, name, role, branch index (None = director)
    ("+998900000001", "Dilnoza Karimova", Role.DIRECTOR, None),
    ("+998900000011", "Aziza Yusupova", Role.BRANCH_ADMIN, 0),
    ("+998900000012", "Sardor Rahimov", Role.SALES_MANAGER, 0),
    ("+998900000013", "Nodir Tursunov", Role.TEACHER, 0),
    ("+998900000014", "Malika Ergasheva", Role.TEACHER, 0),
    ("+998900000021", "Bekzod Aliyev", Role.BRANCH_ADMIN, 1),
    ("+998900000022", "Kamola Saidova", Role.SALES_MANAGER, 1),
    ("+998900000023", "Jasur Xolmatov", Role.TEACHER, 1),
    ("+998900000024", "Shahnoza Qodirova", Role.TEACHER, 1),
]

COURSES = [
    # name, pricing model, months, old price, current price
    ("Matematika 5–6-sinf", "monthly", None, 400_000, 450_000),
    ("Matematika 7–9-sinf", "monthly", None, 450_000, 500_000),
    ("Olimpiada matematikasi", "monthly", None, 600_000, 650_000),
    ("DTM / Abituriyent tayyorlov (9 oy)", "installment", 9, 4_500_000, 4_950_000),
    ("Mental arifmetika (6 oy)", "installment", 6, 2_400_000, 2_700_000),
]


class Command(BaseCommand):
    help = "Create demo data (idempotent)."

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(phone=USERS[0][0]).exists():
            self.stdout.write("Demo data already present.")
            return
        with transaction.atomic():
            self._seed(User)
        self.stdout.write(self.style.SUCCESS("Demo data created."))
        for phone, name, role, _b in USERS:
            self.stdout.write(f"  {phone}  {DEMO_PASSWORD}  {role}  {name}")

    def _seed(self, User):
        today = dates.today()
        branches = [
            Branch.objects.create(
                name="Chilonzor filiali",
                address="Toshkent, Chilonzor tumani, 9-kvartal, 12-uy",
                phone="+998712000101",
                receipt_prefix="CH",
            ),
            Branch.objects.create(
                name="Yunusobod filiali",
                address="Toshkent, Yunusobod tumani, Amir Temur ko'chasi, 108",
                phone="+998712000202",
                receipt_prefix="YU",
            ),
        ]
        for b in branches:
            for i in range(1, 5):
                Room.objects.create(branch=b, name=f"{i}-xona", capacity=12 if i < 4 else 20)

        users = []
        for phone, name, role, b_index in USERS:
            user = User.objects.create_user(phone, name, role, DEMO_PASSWORD)
            user.must_change_password = False
            user.save(update_fields=["must_change_password"])
            if b_index is not None:
                UserBranch.objects.create(user=user, branch=branches[b_index])
            users.append(user)
        director = users[0]

        change_date = today.replace(day=1) - dt.timedelta(days=60)
        for name, model, months, old, new in COURSES:
            course = Course.objects.create(name=name, pricing_model=model, duration_months=months)
            kind = Price.Kind.MONTHLY if model == "monthly" else Price.Kind.FULL_COURSE
            Price.objects.create(
                course=course,
                kind=kind,
                amount=old,
                effective_from=change_date - dt.timedelta(days=365),
                note="Boshlang'ich narx",
                created_by=director,
            )
            Price.objects.create(
                course=course,
                kind=kind,
                amount=new,
                effective_from=change_date,
                note="Narx oshirildi",
                created_by=director,
            )

        InstallmentTemplate.objects.create(
            name="Teng 3 qism (har oyda)", parts_count=3, split_mode="equal", first_due="on_start"
        )
        custom = InstallmentTemplate.objects.create(
            name="40/30/30, har oyning 5-sanasi",
            parts_count=3,
            split_mode="custom",
            first_due="fixed_day",
            due_day_of_month=5,
        )
        for i, bp in enumerate([4000, 3000, 3000]):
            InstallmentTemplatePart.objects.create(template=custom, part_no=i + 1, share_bp=bp)
        InstallmentTemplate.objects.create(
            name="Oylik 9 qism",
            parts_count=9,
            split_mode="equal",
            first_due="on_start",
            course=Course.objects.get(name__startswith="DTM"),
        )

        DiscountType.objects.create(name="Aka-uka / opa-singil", kind="percent", value=1000)
        DiscountType.objects.create(
            name="Promo 50 000", kind="fixed", value=50_000, applies_to="monthly"
        )
        DiscountType.objects.create(
            name="Ijtimoiy chegirma", kind="percent", value=2000, allow_custom_value=True
        )
