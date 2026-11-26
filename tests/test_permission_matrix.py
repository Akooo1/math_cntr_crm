"""Server-side role and branch enforcement (docs/SPEC.md 4.5).

Every named URL must appear in `cases()`. A new URL without an entry fails
`test_every_url_is_in_the_matrix`, so nobody can add an endpoint without deciding who may
use it.
"""

import datetime as dt

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.billing.models import DiscountType, InstallmentTemplate, PaymentMethod
from apps.core.dates import today
from apps.core.reports import reports
from apps.core.roles import Role
from apps.core.settings_panel import sections
from apps.crm.models import LeadSource, LeadStage, RefusalReason
from apps.students.models import LeaveReason
from tests.factories import (
    BranchFactory,
    CourseFactory,
    RoomFactory,
    UserFactory,
    make_group,
    make_lead,
    make_student,
)
from tests.urls_inventory import Case, all_url_names

D, A, M, T = Role.DIRECTOR, Role.BRANCH_ADMIN, Role.SALES_MANAGER, Role.TEACHER
ALL = (D, A, M, T)


def only(role_status: dict, default: int) -> dict:
    return {r: role_status.get(r, default) for r in ALL}


DIRECTOR_ONLY = only({D: 200}, 403)
EVERYONE = only({}, 200)
CRM = {**only({D: 200, A: 200, M: 200}, 403), "anon": 302}
CRM_POST = {**only({D: 302, A: 302, M: 302}, 403), "anon": 302}
# Object in another branch: the director still reaches it; branch staff get 404.
CRM_OTHER = {**only({D: 200, A: 404, M: 404}, 403), "anon": 302}
CRM_OTHER_POST = {**only({D: 302, A: 404, M: 404}, 403), "anon": 302}


def crm_cases(o) -> dict[str, list[Case]]:
    def pair(name, url_fmt, method="get", data=None, key="lead"):
        same = CRM if method == "get" else CRM_POST
        other = CRM_OTHER if method == "get" else CRM_OTHER_POST
        return name, [
            Case(url_fmt.format(o[f"{key}_a"].pk), method, same, data or {}),
            Case(url_fmt.format(o[f"{key}_b"].pk), method, other, data or {}),
        ]

    stage = {"stage": o["stage"].pk}
    return dict(
        [
            ("crm:board", [Case("/lidlar/", expect=CRM), Case("/lidlar/?bosqich=1", expect=CRM)]),
            ("crm:lead_create", [Case("/lidlar/yangi/", expect=CRM)]),
            ("crm:duplicate_check", [Case("/lidlar/dublikat/?phone=901234567", expect=CRM)]),
            (
                "crm:tasks",
                [Case("/vazifalar/", expect=CRM), Case("/vazifalar/?hammasi=1", expect=CRM)],
            ),
            ("crm:trials", [Case("/sinov-darslari/", expect=CRM)]),
            pair("crm:lead", "/lidlar/{}/"),
            pair("crm:lead_edit", "/lidlar/{}/tahrirlash/"),
            pair("crm:refuse", "/lidlar/{}/rad-etish/"),
            pair("crm:convert", "/lidlar/{}/oquvchi/"),
            pair("crm:move", "/lidlar/{}/bosqich/", "post", stage),
            pair("crm:add_activity", "/lidlar/{}/izoh/", "post", {"kind": "note", "text": "x"}),
            pair("crm:reopen", "/lidlar/{}/qayta-ochish/", "post"),
            pair("crm:task_create", "/lidlar/{}/vazifa/", "post", {"title": "x"}),
            pair("crm:trial_book", "/lidlar/{}/sinov-darsi/", "post"),
            pair("crm:task_done", "/vazifalar/{}/bajarildi/", "post", key="task"),
            pair("crm:task_reopen", "/vazifalar/{}/qayta-ochish/", "post", key="task"),
            pair(
                "crm:trial_status",
                "/sinov-darslari/{}/holat/",
                "post",
                {"status": "no_show"},
                key="trial",
            ),
        ]
    )


def expect(get: dict, *, default=403) -> dict:
    return {**only(get, default), "anon": 302}


def students_cases(o) -> dict[str, list[Case]]:
    """Students, groups, attendance, import. `_a` objects are in branch A (teacher_a teaches
    group A); `_b` objects are in branch B."""
    view_all = expect({D: 200, A: 200, M: 200, T: 200})
    manage = expect({D: 200, A: 200})
    manage_other = expect({D: 200, A: 404})
    post_manage = expect({D: 302, A: 302})
    post_manage_other = expect({D: 302, A: 404})
    marker = expect({D: 200, A: 200, T: 200})

    def two(name, fmt, key, same, other, method="get", data=None):
        return name, [
            Case(fmt.format(o[f"{key}_a"].pk), method, same, data or {}),
            Case(fmt.format(o[f"{key}_b"].pk), method, other, data or {}),
        ]

    return dict(
        [
            ("students:list", [Case("/oquvchilar/", expect=view_all)]),
            ("students:create", [Case("/oquvchilar/yangi/", expect=manage)]),
            two(
                "students:detail",
                "/oquvchilar/{}/",
                "student",
                view_all,
                expect({D: 200, A: 404, M: 404, T: 404}),
            ),
            two("students:edit", "/oquvchilar/{}/tahrirlash/", "student", manage, manage_other),
            two(
                "students:enroll",
                "/oquvchilar/{}/guruhga-qoshish/",
                "student",
                manage,
                manage_other,
            ),
            two("students:move", "/qatnashish/{}/otkazish/", "enrollment", manage, manage_other),
            two("students:freeze", "/qatnashish/{}/muzlatish/", "enrollment", manage, manage_other),
            two(
                "students:unfreeze",
                "/qatnashish/{}/davom-ettirish/",
                "enrollment",
                manage,
                manage_other,
            ),
            two("students:leave", "/qatnashish/{}/chiqish/", "enrollment", manage, manage_other),
            ("students:groups", [Case("/guruhlar/", expect=view_all)]),
            ("students:group_create", [Case("/guruhlar/yangi/", expect=manage)]),
            two(
                "students:group",
                "/guruhlar/{}/",
                "group",
                view_all,
                expect({D: 200, A: 404, M: 404, T: 404}),
            ),
            two("students:group_edit", "/guruhlar/{}/tahrirlash/", "group", manage, manage_other),
            two(
                "students:lesson_cancel",
                "/darslar/{}/bekor-qilish/",
                "future_lesson",
                post_manage,
                post_manage_other,
                "post",
                {"reason": "bayram"},
            ),
            two(
                "students:lesson_restore",
                "/darslar/{}/tiklash/",
                "future_lesson",
                post_manage,
                post_manage_other,
                "post",
            ),
            ("students:attendance", [Case("/davomat/", expect=marker)]),
            two(
                "students:attendance_lesson",
                "/davomat/{}/",
                "past_lesson",
                marker,
                expect({D: 200, A: 404, T: 404}),
            ),
            (
                "students:attendance_mark",
                [
                    Case(
                        f"/davomat/{o['past_lesson_a'].pk}/belgilash/",
                        "post",
                        expect({D: 302, A: 302, T: 302}),
                        {"student": o["student_a"].pk, "status": "present"},
                    ),
                    Case(
                        f"/davomat/{o['past_lesson_b'].pk}/belgilash/",
                        "post",
                        expect({D: 302, A: 404, T: 404}),
                        {"student": o["student_b"].pk, "status": "present"},
                    ),
                ],
            ),
            ("students:import", [Case("/import/", expect=manage)]),
            ("students:import_template", [Case("/import/namuna/groups/", expect=manage)]),
            two("students:import_batch", "/import/{}/", "batch", manage, manage_other),
            two(
                "students:import_commit",
                "/import/{}/tasdiqlash/",
                "batch",
                post_manage,
                post_manage_other,
                "post",
            ),
        ]
    )


def billing_cases(o) -> dict[str, list[Case]]:
    """Finance: Direktor everything; admin own branch except reversals/refunds/corrections;
    Sotuv menejeri and O'qituvchi never."""
    fin = expect({D: 200, A: 200})
    fin_other = expect({D: 200, A: 404})
    director = expect({D: 200})

    def two(name, fmt, key, same, other, method="get", data=None):
        return name, [
            Case(fmt.format(o[f"{key}_a"].pk), method, same, data or {}),
            Case(fmt.format(o[f"{key}_b"].pk), method, other, data or {}),
        ]

    return dict(
        [
            ("billing:payments", [Case("/tolovlar/", expect=fin)]),
            (
                "billing:payment_create",
                [
                    Case("/tolovlar/yangi/", expect=fin),
                    Case(f"/tolovlar/yangi/?oquvchi={o['student_a'].pk}", expect=fin),
                ],
            ),
            ("billing:student_search", [Case("/tolovlar/qidirish/?q=Kar", expect=fin)]),
            two("billing:payment", "/tolovlar/{}/", "payment", fin, fin_other),
            two("billing:receipt", "/tolovlar/{}/chek/", "payment", fin, fin_other),
            two("billing:reverse", "/tolovlar/{}/bekor-qilish/", "payment", director, director),
            two("billing:refund", "/hisob/{}/pul-qaytarish/", "student", director, director),
            two("billing:discount_assign", "/hisob/{}/chegirma/", "student", fin, fin_other),
            two("billing:manual_charge", "/hisob/{}/qoshimcha/", "student", director, director),
            two("billing:discount_end", "/chegirmalar/{}/tugatish/", "discount", fin, fin_other),
            two(
                "billing:charge_correct", "/hisoblangan/{}/tuzatish/", "charge", director, director
            ),
            two("billing:plan_edit", "/bolib-tolash-reja/{}/", "plan", fin, fin_other),
            ("billing:debtors", [Case("/qarzdorlar/", expect=fin)]),
            ("billing:cash", [Case("/kassa/", expect=fin)]),
            (
                "billing:cash_close",
                [Case("/kassa/yopish/", "post", expect({D: 302, A: 302}), {"sana": "01.01.2020"})],
            ),
        ]
    )


def reports_cases() -> dict[str, list[Case]]:
    """Reports: each report's own permission (finance reports: Direktor and Filial
    administratori, own branch data only, see apps/reports/tests; staff attendance:
    Direktor). Sotuv menejeri and O'qituvchi never."""
    from apps.core.permissions import get_permission

    def allowed(report):
        return expect({r: 200 for r in get_permission(report.permission).roles})

    missing = expect({D: 404, A: 404})
    report_cases = [Case(f"/hisobotlar/{r.key}/", expect=allowed(r)) for r in reports()]
    report_cases.append(
        Case("/hisobotlar/oylar/?dan=01.01.2026&gacha=31.03.2026", expect=expect({D: 200, A: 200}))
    )
    report_cases.append(Case("/hisobotlar/yoq/", expect=missing))
    return {
        "reports:index": [Case("/hisobotlar/", expect=expect({D: 200, A: 200}))],
        "reports:report": report_cases,
        "reports:excel": [Case(f"/hisobotlar/{r.key}/excel/", expect=allowed(r)) for r in reports()]
        + [Case("/hisobotlar/yoq/excel/", expect=missing)],
    }


@pytest.fixture
def objects(director, branch_a, branch_b, admin_a, teacher_a):
    from apps.billing import services
    from apps.crm import services as crm

    course = CourseFactory()
    room = RoomFactory(branch=branch_a)
    price = services.add_price(
        actor=director, course=course, branch=None, amount=100_000, effective_from="2026-01-01"
    )
    template = InstallmentTemplate.objects.create(name="T", parts_count=2)
    discount = DiscountType.objects.create(name="D", kind="percent", value=1000)
    from apps.billing import services as billing
    from apps.billing.models import Charge
    from apps.students import services as st
    from apps.students.services import importing

    leads = {}
    start = today() - dt.timedelta(days=30)
    monthly = CourseFactory(name="Oylik kurs")
    services.add_price(
        actor=director, course=monthly, branch=None, amount=400_000, effective_from=start
    )
    installment = CourseFactory(name="Bo'lib kurs", pricing_model="installment")
    services.add_price(
        actor=director, course=installment, branch=None, amount=900_000, effective_from=start
    )
    InstallmentTemplate.objects.create(name="2 qism", parts_count=2, course=installment)
    cash = PaymentMethod.objects.get(name="Naqd")
    for key, branch in (("a", branch_a), ("b", branch_b)):
        # Group A is taught by teacher_a; group B by a teacher of branch B.
        teacher = teacher_a if key == "a" else UserFactory(role=T, branches=[branch])
        group = make_group(
            director,
            branch,
            teacher=teacher,
            course=monthly,
            start=start,
            days=(1, 2, 3, 4, 5, 6, 7),
        )
        student = make_student(director, branch)
        enrollment = st.enroll(actor=director, student=student, group=group, start_date=start)
        lessons = group.lessons.order_by("date")
        leads[f"group_{key}"] = group
        leads[f"student_{key}"] = student
        leads[f"enrollment_{key}"] = enrollment
        leads[f"charge_{key}"] = Charge.objects.filter(enrollment=enrollment).first()
        leads[f"payment_{key}"] = billing.payments.record_payment(
            actor=director, student=student, amount=100_000, method=cash, paid_on=today()
        )
        leads[f"discount_{key}"] = billing.discounts.assign(
            actor=director,
            enrollment=enrollment,
            valid_from=today(),
            discount_type=DiscountType.objects.get_or_create(
                name="Promo", kind="fixed", value=10_000
            )[0],
        )
        igroup = make_group(director, branch, teacher=teacher, course=installment, start=start)
        ie = st.enroll(
            actor=director, student=make_student(director, branch), group=igroup, start_date=start
        )
        leads[f"plan_{key}"] = ie.installment_plan
        leads[f"past_lesson_{key}"] = lessons.filter(date__lt=today()).last()
        leads[f"future_lesson_{key}"] = lessons.filter(date__gt=today()).first()
        upload = SimpleUploadedFile("x.xlsx", b"not an excel file")
        leads[f"batch_{key}"] = importing.validate_upload(
            actor=director, kind_key="groups", branch=branch, uploaded_file=upload
        )
        lead = make_lead(director, branch)
        leads[f"lead_{key}"] = lead
        leads[f"task_{key}"] = crm.create_task(
            actor=director, lead=lead, assigned_to=director, due_at=timezone.now(), title="t"
        )
        leads[f"trial_{key}"] = crm.book_trial(
            actor=director,
            lead=lead,
            group=group,
            scheduled_date=leads[f"future_lesson_{key}"].date,
        )
    leads.update(_salary_objects(director, teacher_a, leads["group_b"].teacher))
    leads.update(_store_objects(director, branch_a, branch_b, leads, cash))
    return {
        **leads,
        "stage": LeadStage.objects.get(kind="contacted"),
        "foydalanuvchilar": admin_a,
        # A branch of its own: the toggle case deactivates it, and later cases use branch A.
        "filiallar": BranchFactory(name="Uchinchi filial", receipt_prefix="UF"),
        "xonalar": room,
        "kurslar": course,
        "narxlar": price,
        "bolib-tolash": template,
        "chegirmalar": discount,
        "tolov-usullari": PaymentMethod.objects.filter(provider_code="manual").first(),
        "lid-manbalari": LeadSource.objects.first(),
        "lid-bosqichlari": LeadStage.objects.filter(kind="custom").first()
        or LeadStage.objects.create(name="Qo'shimcha", kind="custom"),
        "rad-sabablari": RefusalReason.objects.first(),
        "ketish-sabablari": LeaveReason.objects.first(),
        "chek": branch_a,
        "umumiy": branch_a,
        "stavkalar": leads["rate"],
        "filial-joylashuvi": branch_a,
        "ish-vaqti": teacher_a,
        "bildirishnomalar": branch_a,
        "telegram": branch_a,
        "xabar-shablonlari": _first_template(),
        "mahsulotlar": leads["product"],
    }


def _store_objects(director, branch_a, branch_b, o, cash):
    """An item and a book stocked in both branches; a paid sale in each branch and a book
    given on account to student A."""
    from apps.store import services as store

    item = store.create_product(
        actor=director, kind="item", name="Suv", price=3000, effective_from=today()
    )
    book = store.create_product(
        actor=director, kind="book", name="Kitob", price=50_000, effective_from=today()
    )
    for branch in (branch_a, branch_b):
        for product in (item, book):
            store.receive_stock(
                actor=director, branch=branch, product=product, quantity=50, received_on=today()
            )
    sale_a = store.sell_items(actor=director, branch=branch_a, lines=[(item, 1)], method=cash)
    sale_b = store.sell_items(actor=director, branch=branch_b, lines=[(item, 1)], method=cash)
    book_a = store.give_book(actor=director, student=o["student_a"], product=book)
    return {
        "branch_a_id": branch_a.pk,
        "branch_b_id": branch_b.pk,
        "product": item,
        "book": book,
        "sale_a": sale_a,
        "sale_b": sale_b,
        "book_sale_a": book_a,
        "cash": cash,
    }


def store_cases(o) -> dict[str, list[Case]]:
    """Store: Direktor everywhere; Filial administratori sells, gives books and records Kirim
    in their own branch; corrections and cancellations are the Direktor's. Sotuv menejeri and
    O'qituvchi never."""
    both = expect({D: 200, A: 200})
    other = expect({D: 200, A: 404})
    director = expect({D: 200})
    post_both = expect({D: 302, A: 302})
    fa, fb = o["branch_a_id"], o["branch_b_id"]
    sa, sb = o["student_a"].pk, o["student_b"].pk
    sell_data = {"filial": fa, f"q_{o['product'].pk}": 1, "method": o["cash"].pk}
    receive_data = {
        "filial": fa,
        "product": o["book"].pk,  # the item is deactivated by the settings toggle case
        "quantity": 1,
        "received_on": today().strftime("%d.%m.%Y"),
    }
    return {
        "store:sell": [
            Case("/savdo/", expect=both),
            Case(f"/savdo/?filial={fa}", expect=both),
            Case(f"/savdo/?filial={fb}", expect=other),
            Case("/savdo/", "post", post_both, sell_data),
        ],
        "store:journal": [
            Case("/savdo/jurnal/", expect=both),
            Case("/savdo/jurnal/?dan=01.01.2026&gacha=31.12.2026", expect=both),
        ],
        "store:sale": [
            Case(f"/savdo/{o['sale_a'].pk}/", expect=both),
            Case(f"/savdo/{o['sale_b'].pk}/", expect=other),
        ],
        "store:reverse": [
            Case(f"/savdo/{o['sale_a'].pk}/bekor-qilish/", expect=director),
            Case(f"/savdo/{o['sale_b'].pk}/bekor-qilish/", expect=director),
            Case(
                f"/savdo/{o['book_sale_a'].pk}/bekor-qilish/",
                "post",
                expect({D: 302}),
                {"reason": "x"},
            ),
        ],
        "store:stock": [
            Case("/ombor/", expect=both),
            Case(f"/ombor/?filial={fb}", expect=other),
        ],
        "store:receive": [
            Case(f"/ombor/kirim/?filial={fa}", expect=both),
            Case(f"/ombor/kirim/?filial={fb}", expect=other),
            Case("/ombor/kirim/", "post", post_both, receive_data),
        ],
        "store:correct": [
            Case(f"/ombor/tuzatish/?filial={fa}", expect=director),
            Case(f"/ombor/tuzatish/?filial={fb}", expect=director),
        ],
        "store:product": [
            Case(f"/ombor/mahsulot/{o['product'].pk}/", expect=both),
            Case(f"/ombor/mahsulot/{o['product'].pk}/?filial={fb}", expect=other),
            Case(f"/ombor/mahsulot/{o['product'].pk + 10**6}/", expect=expect({D: 404, A: 404})),
        ],
        "store:give_book": [
            Case(f"/kitob-berish/{sa}/", expect=both),
            Case(f"/kitob-berish/{sb}/", expect=other),
            Case(f"/kitob-berish/{sa}/", "post", post_both, {"book": o["book"].pk, "pay": "later"}),
        ],
        "store:give_group": [
            Case("/guruhga-kitob/", expect=both),
            Case(f"/guruhga-kitob/?guruh={o['group_a'].pk}", expect=both),
            Case(f"/guruhga-kitob/?guruh={o['group_b'].pk}", expect=other),
        ],
    }


def _first_template():
    from apps.telegram.models import Template

    return Template.objects.order_by("pk").first()


def _salary_objects(director, teacher_a, teacher_b):
    """This month closed (teacher_a paid out), next month open with a bonus."""
    from apps.core.datemath import add_months, month_start
    from apps.core.system_settings import set_settings
    from apps.salaries import services as salaries

    month = month_start(today())
    set_settings({"salaries.start_month": month.year * 100 + month.month}, actor=director)
    rate = salaries.add_rate(actor=director, teacher=teacher_b, rate_bp=6500, effective_from=month)
    salaries.close_month(actor=director, month=month)
    payout = salaries.pay_out(actor=director, teacher=teacher_a, month=month, paid_on=today())
    nxt = add_months(month, 1)
    bonus = salaries.add_adjustment(
        actor=director, teacher=teacher_a, month=nxt, kind="bonus", amount=1000, reason="x"
    )
    return {
        "rate": rate,
        "salary_month": month,
        "salary_next": nxt,
        "salary_payout": payout,
        "salary_bonus": bonus,
        "teacher_a": teacher_a,
        "teacher_b": teacher_b,
    }


def staff_cases(o) -> dict[str, list[Case]]:
    """Staff check-in: everyone but the Direktor marks their own arrival; only the
    Direktor sees the board and records arrivals by hand."""
    near = {"lat": "41.2756", "lng": "69.2034", "accuracy": "20"}
    return {
        "staff:check_in": [
            Case("/keldim/", "post", {**only({A: 302, M: 302, T: 302}, 403), "anon": 302}, near)
        ],
        "staff:board": [
            Case("/xodimlar-davomati/", expect=expect({D: 200})),
            Case("/xodimlar-davomati/?sana=01.11.2026", expect=expect({D: 200})),
        ],
        "staff:manual": [
            Case(
                "/xodimlar-davomati/qolda/",
                "post",
                expect({D: 302}),
                {"user": o["teacher_a"].pk, "reason": "x"},
            )
        ],
    }


def telegram_cases(o) -> dict[str, list[Case]]:
    """Messages to parents: Direktor only."""
    data = {"text": "x", "mode": "group", "group": o["group_a"].pk, "action": "preview"}
    return {
        "telegram:send": [
            Case("/ota-onalarga-xabar/", expect=expect({D: 200})),
            Case(f"/ota-onalarga-xabar/?oquvchi={o['student_a'].pk}", expect=expect({D: 200})),
            Case("/ota-onalarga-xabar/", "post", expect({D: 200}), data),
        ]
    }


def salaries_cases(o) -> dict[str, list[Case]]:
    """Salaries: Direktor only; a teacher sees only "Maoshim" (own sheet, no teacher id in
    the URL). Salaries are not branch-scoped: the Direktor reaches every teacher."""
    director, director_post = expect({D: 200}), expect({D: 302})
    teacher = expect({T: 200})
    month, nxt = f"{o['salary_month']:%m.%Y}", f"{o['salary_next']:%m.%Y}"
    ta, tb = o["teacher_a"].pk, o["teacher_b"].pk
    return {
        "salaries:index": [
            Case("/maosh/", expect=director),
            Case(f"/maosh/?oy={month}", expect=director),
            Case(f"/maosh/?oy={month}&excel=1", expect=director),
        ],
        "salaries:sheet": [
            Case(f"/maosh/oqituvchi/{ta}/?oy={month}", expect=director),
            Case(f"/maosh/oqituvchi/{tb}/?oy={nxt}", expect=director),
            Case(f"/maosh/oqituvchi/{o['student_a'].pk + 10**6}/", expect=expect({D: 404})),
        ],
        "salaries:mine": [
            Case("/maoshim/", expect=teacher),
            Case(f"/maoshim/?oy={month}", expect=teacher),
        ],
        "salaries:close": [Case("/maosh/yopish/", "post", director_post, {"oy": nxt})],
        "salaries:adjustment_add": [
            Case(
                f"/maosh/oqituvchi/{tb}/qoshish/",
                "post",
                director_post,
                {"oy": nxt, "kind": "bonus", "amount": "1000", "reason": "x"},
            )
        ],
        "salaries:payout": [
            Case(f"/maosh/oqituvchi/{ta}/berish/", "post", director_post, {"oy": month})
        ],
        "salaries:adjustment_delete": [
            Case(f"/maosh/qoshimcha/{o['salary_bonus'].pk}/ochirish/", "post", director_post)
        ],
        "salaries:payout_cancel": [
            Case(
                f"/maosh/berilgan/{o['salary_payout'].pk}/bekor-qilish/",
                "post",
                director_post,
                {"reason": "x"},
            )
        ],
    }


def alerts_cases(o) -> dict[str, list[Case]]:
    """Warnings: everyone signed in has the list (each sees only their kinds); a warning
    in another branch is 404 for branch staff. A teacher closes only warnings given to them."""
    from apps.alerts.models import Task

    def task(branch_key):
        return Task.objects.create(
            kind=Task.Kind.LEAD,
            key=f"lead:test:{branch_key}",
            branch=o[f"lead_{branch_key}"].branch,
            lead=o[f"lead_{branch_key}"],
        )

    ta, tb = task("a"), task("b")
    same = expect({D: 302, A: 302, M: 302}, default=404)
    other = expect({D: 302}, default=404)
    return {
        "alerts:list": [
            Case("/ogohlantirishlar/", expect=expect({D: 200, A: 200, M: 200, T: 200})),
            Case("/ogohlantirishlar/?tur=qarz", expect=expect({D: 200, A: 200, M: 200, T: 200})),
        ],
        "alerts:done": [
            Case(f"/ogohlantirishlar/{ta.pk}/bajarildi/", "post", same),
            Case(f"/ogohlantirishlar/{tb.pk}/bajarildi/", "post", other),
        ],
        "alerts:reopen": [
            Case(f"/ogohlantirishlar/{ta.pk}/qayta-ochish/", "post", same),
            Case(f"/ogohlantirishlar/{tb.pk}/qayta-ochish/", "post", other),
        ],
    }


def cases(objects) -> dict[str, list[Case]]:
    c: dict[str, list[Case]] = {
        "core:home": [Case("/", expect={**EVERYONE, "anon": 302})],
        "core:healthz": [Case("/healthz", expect={**EVERYONE, "anon": 200})],
        "core:switch_branch": [
            Case("/filial/", "post", {**only({}, 302), "anon": 302}, {"branch": ""}),
            Case("/filial/", "get", {**only({}, 405), "anon": 302}),
        ],
        "core:audit_log": [Case("/jurnal/", expect={**DIRECTOR_ONLY, "anon": 302})],
        # Global search: everyone signed in; each result group is scoped by its module.
        "core:search": [Case("/qidiruv/?q=Karimov", expect={**EVERYONE, "anon": 302})],
        "accounts:login": [Case("/kirish/", expect={**only({}, 302), "anon": 200})],
        "accounts:logout": [Case("/chiqish/", "post", {**only({}, 302), "anon": 302})],
        "accounts:profile": [Case("/profil/", expect={**EVERYONE, "anon": 302})],
        "accounts:password_change": [Case("/profil/parol/", expect={**EVERYONE, "anon": 302})],
        "settings:index": [Case("/sozlamalar/", expect={**DIRECTOR_ONLY, "anon": 302})],
        "settings:section_list": [],
        "settings:section_create": [],
        "settings:section_edit": [],
        "settings:section_toggle": [],
        "settings:section_action": [],
    }
    c.update(crm_cases(objects))
    c.update(students_cases(objects))
    c.update(billing_cases(objects))
    c.update(reports_cases())
    c.update(salaries_cases(objects))
    c.update(staff_cases(objects))
    c.update(telegram_cases(objects))
    c.update(store_cases(objects))
    c.update(alerts_cases(objects))
    for s in sections():
        base = f"/sozlamalar/{s.slug}/"
        obj = objects[s.slug]
        c["settings:section_list"].append(Case(base, expect={**DIRECTOR_ONLY, "anon": 302}))
        creatable = s.allow_create
        c["settings:section_create"].append(
            Case(base + "yangi/", expect={**only({D: 200 if creatable else 404}, 403), "anon": 302})
        )
        c["settings:section_edit"].append(
            Case(
                f"{base}{obj.pk}/",
                expect={**only({D: 200 if s.allow_edit else 404}, 403), "anon": 302},
            )
        )
        if s.allow_toggle_active:
            c["settings:section_toggle"].append(
                Case(f"{base}{obj.pk}/holat/", "post", {**only({D: 302}, 403), "anon": 302})
            )
        for action in s.actions:
            c["settings:section_action"].append(
                Case(f"{base}{obj.pk}/{action}/", expect={**DIRECTOR_ONLY, "anon": 302})
            )
    return c


@pytest.mark.django_db
def test_every_url_is_in_the_matrix(objects):
    listed = set(cases(objects))
    missing = all_url_names() - listed
    assert not missing, f"Add these URLs to tests/test_permission_matrix.py: {sorted(missing)}"


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["anon", D, A, M, T])
def test_role_matrix(client, objects, users_by_role, who):
    if who != "anon":
        client.force_login(users_by_role[who], backend="apps.accounts.backends.PhoneBackend")
    failures = []
    for name, items in cases(objects).items():
        for case in items:
            resp = getattr(client, case.method)(case.url, case.data)
            expected = case.expect[who]
            if resp.status_code != expected:
                failures.append(
                    f"{case.method.upper()} {case.url} ({name}): {resp.status_code} != {expected}"
                )
            if who != "anon" and case.url == "/chiqish/":
                client.force_login(
                    users_by_role[who], backend="apps.accounts.backends.PhoneBackend"
                )
    assert not failures, "\n".join(failures)


@pytest.mark.django_db
class TestBranchScope:
    def test_admin_cannot_switch_to_foreign_branch(self, login, admin_a, branch_a, branch_b):
        c = login(admin_a)
        c.post("/filial/", {"branch": branch_b.pk})
        assert c.session.get("branch_filter") is None

    def test_director_can_switch_to_any_branch(self, login, director, branch_a, branch_b):
        c = login(director)
        c.post("/filial/", {"branch": branch_b.pk})
        assert c.session.get("branch_filter") == branch_b.pk

    def test_switch_redirect_stays_on_site(self, login, director):
        c = login(director)
        resp = c.post("/filial/", {"branch": "", "next": "https://evil.example/"})
        assert resp["Location"] == "/"

    def test_settings_services_reject_non_director(self, admin_a, branch_a):
        from django.core.exceptions import PermissionDenied

        from apps.billing import services

        with pytest.raises(PermissionDenied):
            services.add_price(
                actor=admin_a,
                course=CourseFactory(),
                branch=branch_a,
                amount=1,
                effective_from="2026-01-01",
            )
