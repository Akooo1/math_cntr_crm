"""List headers show the total, "X / Y" when filtered, and money lists the sum of the shown
rows; pagination reads "1–25 / 248" (core.listing, components/count.html, pagination.html)."""

import datetime as dt

import pytest
from django.test import RequestFactory

from apps.billing import services as billing
from apps.billing.tests.helpers import D, cash, clock, group, monthly, terminal  # noqa: F401
from apps.core import listing
from apps.core.templatetags.mm import relative_label
from apps.students.models import Student
from tests.factories import make_lead, make_student

pytestmark = pytest.mark.django_db


def login(client, user):
    client.force_login(user, backend="apps.accounts.backends.PhoneBackend")


def count_pill(resp) -> str:
    """The header count as rendered: data-count="248" or "25/248"."""
    html = resp.content.decode()
    marker = 'data-count="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


class TestStudents:
    def test_total_and_filtered_count(self, client, admin_a, branch_a, branch_b, director):
        for last in ("Valiyev", "Karimov", "Toshev"):
            make_student(admin_a, branch_a, last_name=last)
        make_student(director, branch_b, last_name="Boshqa")  # another branch: not counted
        login(client, admin_a)

        resp = client.get("/oquvchilar/")
        t = resp.context["totals"]
        assert (t.total, t.shown, t.filtered) == (3, 3, False)
        assert count_pill(resp) == "3"

        resp = client.get("/oquvchilar/?q=valiyev")
        t = resp.context["totals"]
        assert (t.total, t.shown, t.filtered) == (3, 1, True)
        assert count_pill(resp) == "1/3"
        assert t.amount is None  # not a money list

    def test_pagination_reads_range_of_total(self, client, admin_a, branch_a):
        for i in range(27):
            make_student(admin_a, branch_a, last_name=f"Familiya{i:02d}")
        login(client, admin_a)
        page1 = client.get("/oquvchilar/").content.decode()
        page2 = client.get("/oquvchilar/?page=2").content.decode()
        assert "1–25 / 27" in page1
        assert "26–27 / 27" in page2

    def test_sort_by_name_descending(self, client, admin_a, branch_a):
        for last in ("Aliyev", "Zokirov"):
            make_student(admin_a, branch_a, last_name=last)
        login(client, admin_a)
        resp = client.get("/oquvchilar/?tartib=-ism")
        names = [s.last_name for s in resp.context["page"].object_list]
        assert names == ["Zokirov", "Aliyev"]
        assert resp.context["sort"].desc is True


class TestPayments:
    def test_count_and_net_sum_of_shown_rows(
        self,
        client,
        director,
        admin_a,
        branch_a,
        group,  # noqa: F811
        cash,  # noqa: F811
        terminal,  # noqa: F811
    ):
        student = make_student(admin_a, branch_a)
        kw = {"actor": admin_a, "student": student, "paid_on": D(2026, 11, 16)}
        billing.payments.record_payment(amount=300_000, method=cash, **kw)
        card = billing.payments.record_payment(amount=200_000, method=terminal, **kw)
        billing.payments.reverse_payment(actor=director, payment=card, reason="Xato")
        login(client, admin_a)

        resp = client.get("/tolovlar/")
        t = resp.context["totals"]
        # Two payments and one reversal; the sum is net, like the Excel export's total.
        assert (t.shown, t.amount) == (3, 300_000)
        assert "300\u202f000\u202fso&#x27;m" in resp.content.decode()  # the header sum

        resp = client.get(f"/tolovlar/?usul={cash.pk}")
        t = resp.context["totals"]
        assert (t.total, t.shown, t.amount) == (3, 1, 300_000)
        assert count_pill(resp) == "1/3"

    def test_old_payments_count_in_the_total_only(
        self,
        client,
        admin_a,
        branch_a,
        clock,  # noqa: F811
        group,  # noqa: F811
        cash,  # noqa: F811
    ):
        student = make_student(admin_a, branch_a)
        clock.move_to("2026-09-01 10:00+05:00")  # outside the default 30-day window
        billing.payments.record_payment(
            actor=admin_a, student=student, amount=100_000, method=cash, paid_on=D(2026, 9, 1)
        )
        clock.move_to("2026-11-16 10:00+05:00")
        billing.payments.record_payment(
            actor=admin_a, student=student, amount=100_000, method=cash, paid_on=D(2026, 11, 16)
        )
        login(client, admin_a)
        t = client.get("/tolovlar/").context["totals"]
        assert (t.total, t.shown, t.amount, t.filtered) == (2, 1, 100_000, True)


class TestLeads:
    def test_board_counts_and_filters(self, client, manager_a, branch_a, branch_b, director):
        make_lead(manager_a, branch_a, full_name="Aliyev Bobur")
        make_lead(manager_a, branch_a, full_name="Karimova Dilnoza")
        make_lead(manager_a, branch_a, full_name="Karimov Sardor")
        make_lead(director, branch_b, full_name="Boshqa Filial")
        login(client, manager_a)

        t = client.get("/lidlar/").context["totals"]
        assert (t.total, t.shown, t.filtered) == (3, 3, False)

        resp = client.get("/lidlar/?q=karimov")
        t = resp.context["totals"]
        assert (t.total, t.shown, t.filtered) == (3, 2, True)
        assert count_pill(resp) == "2/3"

        stage = resp.context["columns"][0]["stage"]
        t = client.get(f"/lidlar/?bosqich={stage.pk}").context["totals"]
        assert (t.total, t.shown, t.filtered) == (3, 3, True)  # all new leads are in stage 1


class TestHelpers:
    def test_totals_from_counts_and_querysets(self, admin_a, branch_a):
        make_student(admin_a, branch_a)
        everything = Student.objects.all()
        assert listing.totals(everything) == listing.Totals(total=1, shown=1)
        t = listing.totals(everything, everything.none(), amount=5)
        assert (t.total, t.shown, t.filtered, t.amount) == (1, 0, True, 5)
        assert listing.totals(10, 4, filtered=False).filtered is False

    def test_sort_links_toggle_and_keep_other_params(self):
        request = RequestFactory().get("/x/?q=ali&page=3&tartib=ism")
        rows, sort = listing.sort_rows(
            request, [{"n": 2}, {"n": 1}], {"ism": lambda r: r["n"], "kun": len}, default="ism"
        )
        assert [r["n"] for r in rows] == [1, 2]
        assert sort.url["ism"] == "q=ali&tartib=-ism"  # same column: flip, back to page 1
        assert sort.url["kun"] == "q=ali&tartib=kun"

    def test_unknown_sort_key_falls_back_to_default(self):
        request = RequestFactory().get("/x/?tartib=-hack")
        _, sort = listing.sort_rows(request, [], {"ism": len}, default="-ism")
        assert (sort.key, sort.desc) == ("ism", True)


class TestRelativeTime:
    NOW = dt.datetime(2026, 11, 25, 14, 32, tzinfo=dt.timezone(dt.timedelta(hours=5)))

    @pytest.mark.parametrize(
        ("delta", "expected"),
        [
            (dt.timedelta(seconds=20), "hozirgina"),
            (dt.timedelta(minutes=5), "5 daqiqa oldin"),
            (dt.timedelta(hours=2), "2 soat oldin"),
            (dt.timedelta(days=1), "kecha 14:32"),
            (dt.timedelta(days=3), "3 kun oldin"),
            (dt.timedelta(days=30), "26.10.2026"),
            (-dt.timedelta(hours=3), "3 soatdan so'ng"),
        ],
    )
    def test_labels(self, delta, expected):
        assert relative_label(self.NOW - delta, now=self.NOW) == expected


class TestGlobalSearch:
    def test_results_follow_role_scope(self, client, admin_a, teacher_a, manager_a, branch_a):
        make_student(admin_a, branch_a, last_name="Qidiruvov")
        make_lead(manager_a, branch_a, full_name="Qidiruvova Lola")

        login(client, admin_a)
        groups = {g["provider"].key for g in client.get("/qidiruv/?q=qidiruv").context["groups"]}
        assert groups == {"students", "leads"}

        # The teacher has no groups, so sees none of these students, and never leads.
        login(client, teacher_a)
        assert client.get("/qidiruv/?q=qidiruv").context["groups"] == []

    def test_palette_gets_a_partial_and_short_queries_find_nothing(self, client, admin_a):
        login(client, admin_a)
        resp = client.get("/qidiruv/?q=a", HTTP_HX_REQUEST="true")
        assert resp.context["groups"] == []
        assert "<html" not in resp.content.decode()


class TestWarnings:
    def test_total_and_filtered_by_kind(self, client, admin_a, branch_a):
        from apps.alerts.models import Task

        for i in range(2):
            Task.objects.create(
                kind=Task.Kind.LEAD,
                key=f"lead:t{i}",
                branch=branch_a,
                lead=make_lead(admin_a, branch_a),
            )
        Task.objects.create(
            kind=Task.Kind.ABSENCE,
            key="absence:t",
            branch=branch_a,
            student=make_student(admin_a, branch_a),
            details={"missed": 2},
        )
        login(client, admin_a)
        resp = client.get("/ogohlantirishlar/")
        assert count_pill(resp) == "3"
        resp = client.get("/ogohlantirishlar/?tur=lid")
        t = resp.context["totals"]
        assert (t.total, t.shown, t.filtered) == (3, 2, True)
        assert count_pill(resp) == "2/3"


class TestExpenses:
    def test_count_and_sum(self, client, admin_a, branch_a, director):
        from apps.expenses import services
        from apps.expenses.models import Category

        rent = Category.objects.get(name="Ijara")
        today = dt.date.today()
        for amount in (100_000, 250_000):
            services.record(
                actor=admin_a, branch=branch_a, category=rent, amount=amount, spent_on=today
            )
        old = services.record(
            actor=admin_a,
            branch=branch_a,
            category=rent,
            amount=1_000,
            spent_on=today - dt.timedelta(days=40),
        )
        assert old.pk
        login(client, admin_a)
        resp = client.get("/xarajatlar/")
        t = resp.context["totals"]
        assert (t.total, t.shown, t.amount) == (3, 2, 350_000)
        assert count_pill(resp) == "2/3"
