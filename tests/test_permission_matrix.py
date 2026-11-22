"""Server-side role and branch enforcement (docs/SPEC.md 4.5).

Every named URL must appear in `cases()`. A new URL without an entry fails
`test_every_url_is_in_the_matrix`, so nobody can add an endpoint without deciding who may
use it.
"""

import pytest
from django.utils import timezone

from apps.billing.models import DiscountType, InstallmentTemplate, PaymentMethod
from apps.core.dates import today
from apps.core.roles import Role
from apps.core.settings_panel import sections
from apps.crm.models import LeadSource, LeadStage, RefusalReason
from tests.factories import CourseFactory, RoomFactory, make_lead
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
            pair(
                "crm:trial_status",
                "/sinov-darslari/{}/holat/",
                "post",
                {"status": "no_show"},
                key="trial",
            ),
        ]
    )


@pytest.fixture
def objects(director, branch_a, branch_b, admin_a):
    from apps.billing import services
    from apps.crm import services as crm

    course = CourseFactory()
    room = RoomFactory(branch=branch_a)
    price = services.add_price(
        actor=director, course=course, branch=None, amount=100_000, effective_from="2026-01-01"
    )
    template = InstallmentTemplate.objects.create(name="T", parts_count=2)
    discount = DiscountType.objects.create(name="D", kind="percent", value=1000)
    leads = {}
    for key, branch in (("a", branch_a), ("b", branch_b)):
        lead = make_lead(director, branch)
        leads[f"lead_{key}"] = lead
        leads[f"task_{key}"] = crm.create_task(
            actor=director, lead=lead, assigned_to=director, due_at=timezone.now(), title="t"
        )
        leads[f"trial_{key}"] = crm.book_trial(actor=director, lead=lead, scheduled_date=today())
    return {
        **leads,
        "stage": LeadStage.objects.get(kind="contacted"),
        "foydalanuvchilar": admin_a,
        "filiallar": branch_a,
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
        "chek": branch_a,
        "umumiy": branch_a,
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
