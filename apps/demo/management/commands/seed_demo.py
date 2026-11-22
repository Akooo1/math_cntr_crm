"""Demo data. Phase 1 content: branches, staff for every role, rooms, courses, prices,
installment templates and discount types. Later phases extend this command.

Safe to run twice: it does nothing when demo users already exist.
"""

import datetime as dt
import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.billing.models import DiscountType, InstallmentTemplate, InstallmentTemplatePart, Price
from apps.core import dates
from apps.core.roles import Role
from apps.crm import services as crm_services
from apps.crm.models import Lead, LeadSource, LeadStage, RefusalReason, TrialLesson
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


FIRST_NAMES = [
    "Aziz",
    "Bobur",
    "Dilshod",
    "Elyor",
    "Farrux",
    "Jahongir",
    "Javohir",
    "Otabek",
    "Sardor",
    "Shoxrux",
    "Ulug'bek",
    "Asal",
    "Dilnoza",
    "Gulnoza",
    "Kamola",
    "Madina",
    "Malika",
    "Nilufar",
    "Sevara",
    "Shahzoda",
    "Zarina",
    "Mohinur",
    "Ozoda",
    "Sanjar",
    "Temur",
]
LAST_NAMES = [
    "Abdullayev",
    "Aliyev",
    "Karimov",
    "Rahimov",
    "Tursunov",
    "Yusupov",
    "Ergashev",
    "Qodirov",
    "Xolmatov",
    "Saidov",
    "Normatov",
    "Mirzayev",
    "To'xtayev",
    "G'aniyev",
    "Nazarov",
    "Sobirov",
    "Islomov",
    "Hamidov",
]
PARENT_NAMES = ["Anvar", "Bahodir", "Dilfuza", "Gulchehra", "Ravshan", "Shavkat", "Zulfiya"]
NOTES = ["", "", "Onasi qo'ng'iroq qildi", "Kechki guruh kerak", "Instagramdagi reklamadan"]
CALL_NOTES = [
    "Narxni so'radi, o'ylab ko'rishini aytdi",
    "Dars vaqtlarini so'radi",
    "Ota-onasi bilan maslahatlashadi",
    "Sinov darsiga qiziqdi",
]
TASK_TITLES = ["Qayta qo'ng'iroq qilish", "Narxlarni yuborish", "Sinov darsini eslatish"]


class Command(BaseCommand):
    help = "Create demo data (idempotent)."

    def handle(self, *args, **options):
        User = get_user_model()
        created = False
        if not User.objects.filter(phone=USERS[0][0]).exists():
            with transaction.atomic():
                self._seed(User)
            created = True
        if not Lead.objects.exists():
            with transaction.atomic():
                self._seed_crm(User)
            created = True
        if not created:
            self.stdout.write("Demo data already present.")
            return
        self.stdout.write(self.style.SUCCESS("Demo data created."))
        for phone, name, role, _b in USERS:
            self.stdout.write(f"  {phone}  {DEMO_PASSWORD}  {role}  {name}")

    def _seed_crm(self, User):
        """About 45 leads per the brief: every stage, tasks, trials, a few conversions."""
        rnd = random.Random(42)
        now = dates.now()
        today = dates.today()
        sources = list(LeadSource.objects.filter(is_active=True))
        reasons = list(RefusalReason.objects.filter(is_active=True))
        courses = list(Course.objects.all())
        stages = {s.kind: s for s in LeadStage.objects.exclude(kind="custom")}
        branches = list(Branch.objects.order_by("id"))
        phone_seq = iter(range(1_000_000, 9_999_999, 7_919))
        plan = ["new"] * 8 + ["contacted"] * 7 + ["trial_booked"] * 6 + ["trial_attended"] * 5
        plan += ["won"] * 4 + ["lost"] * 5
        for b_index, branch in enumerate(branches):
            manager = User.objects.get(phone=USERS[2 + b_index * 4][0])
            admin = User.objects.get(phone=USERS[1 + b_index * 4][0])
            for i, kind in enumerate(plan):
                first = rnd.choice(FIRST_NAMES)
                last = rnd.choice(LAST_NAMES)
                phone = f"+99893{next(phone_seq):07d}"
                lead = crm_services.create_lead(
                    actor=manager,
                    branch=branch,
                    data={
                        "full_name": f"{last} {first}",
                        "phone": phone,
                        "source": rnd.choice(sources),
                        "course": rnd.choice(courses),
                        "manager": manager,
                        "notes": rnd.choice(NOTES),
                    },
                    confirm_duplicate=True,
                )
                if kind != "new":
                    crm_services.add_activity(
                        actor=manager, lead=lead, kind="call", text=rnd.choice(CALL_NOTES)
                    )
                if kind in ("contacted", "trial_booked", "trial_attended", "won", "lost"):
                    crm_services.change_stage(actor=manager, lead=lead, stage=stages["contacted"])
                if kind in ("trial_booked", "trial_attended", "won"):
                    trial = crm_services.book_trial(
                        actor=manager, lead=lead, scheduled_date=today + dt.timedelta(days=i % 5)
                    )
                    if kind in ("trial_attended", "won"):
                        crm_services.set_trial_status(actor=manager, trial=trial, status="attended")
                if kind == "won":
                    crm_services.convert(
                        actor=admin,
                        lead=lead,
                        student_data={
                            "first_name": first,
                            "last_name": last,
                            "phone": phone,
                            "parent_name": f"{last} {rnd.choice(PARENT_NAMES)}",
                            "parent_phone": f"+99890{next(phone_seq):07d}",
                        },
                        confirm_duplicate=True,
                    )
                elif kind == "lost":
                    crm_services.refuse(
                        actor=manager, lead=lead, reason=rnd.choice(reasons), note=""
                    )
                else:
                    # Overdue, today and upcoming follow-ups.
                    offset = [-2, -1, 0, 0, 1, 2, 3][i % 7]
                    due = now.replace(hour=10, minute=0, second=0, microsecond=0)
                    crm_services.create_task(
                        actor=manager,
                        lead=lead,
                        assigned_to=manager,
                        due_at=due + dt.timedelta(days=offset),
                        title=rnd.choice(TASK_TITLES),
                    )
            # One trial from yesterday whose result was never marked.
            lead = Lead.objects.filter(branch=branch, stage=stages["trial_booked"]).first()
            if lead:
                TrialLesson.objects.create(lead=lead, scheduled_date=today - dt.timedelta(days=1))

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
