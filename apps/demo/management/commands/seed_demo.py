"""Demo data. Phase 1 content: branches, staff for every role, rooms, courses, prices,
installment templates and discount types. Later phases extend this command.

Safe to run twice: it does nothing when demo users already exist.
"""

import datetime as dt
import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.billing import services as billing
from apps.billing.models import (
    ChargeNet,
    DiscountType,
    InstallmentTemplate,
    InstallmentTemplatePart,
    Payment,
    PaymentMethod,
    Price,
)
from apps.core import dates
from apps.core.roles import Role
from apps.core.system_settings import get_setting, set_settings
from apps.crm import services as crm_services
from apps.crm.models import Lead, LeadSource, LeadStage, RefusalReason, TrialLesson
from apps.settings.models import Branch, Course, Room, UserBranch
from apps.students import selectors as student_selectors
from apps.students import services as student_services
from apps.students.models import Attendance, Enrollment, Group, Lesson, Student

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
        if not Group.objects.exists():
            with transaction.atomic():
                self._seed_groups(User)
            created = True
        if not Lead.objects.exists():
            with transaction.atomic():
                self._seed_crm(User)
            created = True
        if not Payment.objects.exists():
            with transaction.atomic():
                self._seed_money(User)
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
        upcoming = {}
        for lesson in Lesson.objects.filter(
            date__gte=today, date__lte=today + dt.timedelta(days=7), status="scheduled"
        ).select_related("group"):
            upcoming.setdefault(lesson.group.branch_id, []).append((lesson.group, lesson.date))
        plan = ["new"] * 8 + ["contacted"] * 7 + ["trial_booked"] * 6 + ["trial_attended"] * 5
        plan += ["won"] * 4 + ["lost"] * 5
        for b_index, branch in enumerate(branches):
            manager = User.objects.get(phone=USERS[2 + b_index * 4][0])
            admin = User.objects.get(phone=USERS[1 + b_index * 4][0])
            trial_slots = upcoming.get(branch.pk) or []
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
                    group, day = trial_slots[(i + b_index) % len(trial_slots)]
                    trial = crm_services.book_trial(
                        actor=manager, lead=lead, group=group, scheduled_date=day
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
            # One trial from a past lesson whose result was never marked.
            lead = Lead.objects.filter(branch=branch, stage=stages["trial_booked"]).first()
            past = (
                Lesson.objects.filter(group__branch=branch, date__lt=today)
                .order_by("-date")
                .first()
            )
            if lead and past:
                TrialLesson.objects.create(
                    lead=lead, group=past.group, lesson=past, scheduled_date=past.date
                )
            # Half of the converted leads are already in a group; the rest await enrollment.
            for n, lead in enumerate(Lead.objects.filter(branch=branch, student__isnull=False)):
                if n % 2:
                    continue
                group = (
                    Group.objects.filter(branch=branch, course=lead.course)
                    .exclude(status="finished")
                    .first()
                )
                if group:
                    student_services.enroll(
                        actor=admin,
                        student=lead.student,
                        group=group,
                        start_date=max(today, group.start_date),
                        capacity_override=True,
                    )

    def _seed_money(self, User):
        """Payments for the charges the enrollments created: most families pay on time, some
        owe, a few overpaid; one reversal and one refund per branch; past days closed except
        the last two (so the cash report shows an open day and the dashboard a reminder)."""
        rnd = random.Random(11)
        today = dates.today()
        director = User.objects.get(phone=USERS[0][0])
        methods = list(PaymentMethod.objects.filter(provider_code="manual", is_active=True))
        old_window = get_setting("billing.backdate_days")
        set_settings({"billing.backdate_days": 31}, actor=director)  # demo history only
        # Discounts: a few siblings get 10% from next month on.
        sibling = DiscountType.objects.get(name="Aka-uka / opa-singil")
        for e in Enrollment.objects.filter(status="active", group__course__pricing_model="monthly")[
            :4
        ]:
            billing.discounts.assign(
                actor=director,
                enrollment=e,
                discount_type=sibling,
                valid_from=dates.add_months(today.replace(day=1), 1),
                reason="Ikkinchi farzand",
            )
        payments = []  # (date, student, amount)
        for student in Student.objects.all():
            charges = list(
                ChargeNet.objects.filter(student=student, due_date__lte=today, net__gt=0).order_by(
                    "due_date"
                )
            )
            if not charges:
                continue
            habit = rnd.random()
            if habit < 0.12:
                charges = charges[:-2]  # two months behind
            elif habit < 0.30:
                charges = charges[:-1]  # behind on the latest charge
            for c in charges:
                day = min(today, c.due_date + dt.timedelta(days=rnd.randint(0, 6)))
                if (today - day).days > 30:
                    day = today - dt.timedelta(days=rnd.randint(20, 30))
                payments.append((day, student, c.net))
            if habit > 0.95:
                payments.append((today, student, 100_000))  # overpaid: credit
        payments.sort(key=lambda p: p[0])
        admins = {
            b.pk: User.objects.get(phone=USERS[1 + i * 4][0])
            for i, b in enumerate(Branch.objects.order_by("id"))
        }
        recorded = []
        for day, student, amount in payments:
            if (today - day).days > 31:
                continue
            recorded.append(
                billing.payments.record_payment(
                    actor=admins[student.branch_id],
                    student=student,
                    amount=amount,
                    method=rnd.choice(methods),
                    paid_on=day,
                    comment="",
                )
            )
        set_settings({"billing.backdate_days": old_window}, actor=director)
        # One wrong payment reversed and re-entered today, one refund of a credit, per branch.
        for branch_id, admin in admins.items():
            student = Student.objects.filter(branch_id=branch_id).first()
            wrong = billing.payments.record_payment(
                actor=admin, student=student, amount=1_500_000, method=methods[0], paid_on=today
            )
            billing.payments.reverse_payment(
                actor=director,
                payment=wrong,
                reason="Summa xato kiritildi: 150 000 o'rniga 1 500 000",
            )
            billing.payments.record_payment(
                actor=admin, student=student, amount=150_000, method=methods[0], paid_on=today
            )
            credit = next(
                (
                    p.student
                    for p in recorded
                    if p.branch_id == branch_id and billing.payments.credit_of(p.student_id) > 0
                ),
                None,
            )
            if credit is not None:
                billing.payments.refund(
                    actor=director,
                    student=credit,
                    amount=50_000,
                    method=methods[0],
                    reason="Ota-onasi so'radi",
                )
        # Close every past day with payments except the last two.
        days = sorted(
            {
                (p.branch_id, p.paid_on)
                for p in Payment.objects.filter(paid_on__lt=today - dt.timedelta(days=2))
            }
        )
        for branch_id, day in days:
            billing.cash.close_day(
                actor=admins[branch_id], branch=Branch.objects.get(pk=branch_id), day=day
            )

    def _seed_groups(self, User):
        """9 groups with schedules and lessons, ~52 students, attendance, lifecycle examples."""
        rnd = random.Random(7)
        today = dates.today()
        # Groups started on the Monday about 12 weeks ago, so there is history to show.
        start = today - dt.timedelta(days=today.weekday() + 7 * 12)
        courses = {c.name: c for c in Course.objects.all()}
        branches = list(Branch.objects.order_by("id"))
        mwf = [
            (1, dt.time(15, 0), dt.time(16, 30)),
            (3, dt.time(15, 0), dt.time(16, 30)),
            (5, dt.time(15, 0), dt.time(16, 30)),
        ]
        tts = [
            (2, dt.time(17, 0), dt.time(18, 30)),
            (4, dt.time(17, 0), dt.time(18, 30)),
            (6, dt.time(10, 0), dt.time(11, 30)),
        ]
        plan = [
            # branch, name, course, teacher idx, slots, months (None = open)
            (0, "5-6 A", "Matematika 5–6-sinf", 3, mwf, None),
            (0, "7-9 A", "Matematika 7–9-sinf", 4, tts, None),
            (0, "Olimpiada 1", "Olimpiada matematikasi", 3, tts, None),
            (0, "DTM-1", "DTM / Abituriyent tayyorlov (9 oy)", 4, mwf, 9),
            (
                0,
                "Mental-1",
                "Mental arifmetika (6 oy)",
                3,
                [(6, dt.time(12, 0), dt.time(13, 0)), (7, dt.time(12, 0), dt.time(13, 0))],
                6,
            ),
            (1, "5-6 B", "Matematika 5–6-sinf", 7, tts, None),
            (1, "7-9 B", "Matematika 7–9-sinf", 8, mwf, None),
            (1, "DTM-2", "DTM / Abituriyent tayyorlov (9 oy)", 7, tts, 9),
            (1, "Mental-2", "Mental arifmetika (6 oy)", 8, mwf, 6),
        ]
        groups_by_branch = {b.pk: [] for b in branches}
        for b_index, name, course, t_index, slots, months in plan:
            branch = branches[b_index]
            admin = User.objects.get(phone=USERS[1 + b_index * 4][0])
            group = Group(
                branch=branch,
                course=courses[course],
                teacher=User.objects.get(phone=USERS[t_index][0]),
                room=Room.objects.filter(branch=branch).order_by("name")[
                    len(groups_by_branch[branch.pk]) % 4
                ],
                name=name,
                start_date=start,
                end_date=dates.add_months(start, months) if months else None,
                capacity=10,
            )
            student_services.save_group(
                actor=admin,
                group=group,
                slots=[
                    {"weekday": d, "start_time": a, "end_time": e, "room": None}
                    for d, a, e in slots
                ],
            )
            groups_by_branch[branch.pk].append(group)

        seq = iter(range(2_000_000, 9_999_999, 6_421))
        for b_index, branch in enumerate(branches):
            admin = User.objects.get(phone=USERS[1 + b_index * 4][0])
            groups = groups_by_branch[branch.pk]
            for n in range(26):
                last, first = rnd.choice(LAST_NAMES), rnd.choice(FIRST_NAMES)
                student = student_services.create_student(
                    actor=admin,
                    branch=branch,
                    data={
                        "first_name": first,
                        "last_name": last,
                        "birth_date": dt.date(2008 + n % 9, 1 + n % 12, 1 + n % 27),
                        "phone": f"+99894{next(seq):07d}" if n % 3 else "",
                        "parent_name": f"{last} {rnd.choice(PARENT_NAMES)}",
                        "parent_phone": f"+99891{next(seq):07d}",
                    },
                )
                group = groups[n % len(groups)]
                joined = start if n % 5 else start + dt.timedelta(days=30 + n)
                student_services.enroll(
                    actor=admin,
                    student=student,
                    group=group,
                    start_date=joined,
                    capacity_override=True,
                )
            # Lifecycle examples: one freeze, one leave, one move (all in the past).
            enrollments = list(Enrollment.objects.filter(group__branch=branch, status="active"))
            frozen, left, moved = enrollments[1], enrollments[2], enrollments[3]
            student_services.freeze(
                actor=admin,
                enrollment=frozen,
                from_date=today - dt.timedelta(days=10),
                reason="Kasal, shifokor tavsiyasi",
            )
            student_services.leave(
                actor=admin,
                enrollment=left,
                end_date=today - dt.timedelta(days=20),
                reason="Boshqa shaharga ko'chib ketdi",
            )
            target = (
                next(
                    g
                    for g in groups
                    if g.pk != moved.group_id and g.course_id == moved.group.course_id
                )
                if any(
                    g.pk != moved.group_id and g.course_id == moved.group.course_id for g in groups
                )
                else next(g for g in groups if g.pk != moved.group_id)
            )
            student_services.move(
                actor=admin,
                enrollment=moved,
                target_group=target,
                effective_date=today - dt.timedelta(days=14),
                reason="Vaqt to'g'ri kelmadi",
                capacity_override=True,
            )

        # Attendance for past lessons (bulk, ~88% present).
        rows = []
        for lesson in Lesson.objects.filter(date__lt=today).select_related("group"):
            roster = student_selectors.roster(lesson)
            if not roster:
                continue
            teacher = lesson.group.teacher
            for e in roster:
                rows.append(
                    Attendance(
                        lesson=lesson,
                        enrollment=e,
                        student_id=e.student_id,
                        status="present" if rnd.random() < 0.88 else "absent",
                        marked_by=teacher,
                    )
                )
            lesson.status = "held"
            lesson.save(update_fields=["status"])
        Attendance.objects.bulk_create(rows)
        # One cancelled holiday lesson next week.
        holiday = (
            Lesson.objects.filter(date__gt=today + dt.timedelta(days=7)).order_by("date").first()
        )
        if holiday:
            holiday.status = "cancelled"
            holiday.cancel_reason = "Bayram kuni"
            holiday.save(update_fields=["status", "cancel_reason"])

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
