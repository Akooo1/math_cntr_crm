"""Reports and the dashboard: numbers match the ledger, branch scope holds, exports are
Uzbek. Clock: Monday 16.11.2026 10:00 Tashkent (billing test helpers)."""

import datetime as dt
import io

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.billing import selectors as billing_selectors
from apps.billing import services as billing
from apps.billing.models import Charge
from apps.billing.tests.helpers import MWF, NOW, D, net
from apps.core.reports import Params, get_report, reports
from apps.crm import services as crm
from apps.crm.models import LeadSource
from apps.reports import dashboard, queries
from apps.students import services as st
from tests.factories import make_group, make_lead, make_student, page_text

pytestmark = pytest.mark.django_db

NOV, OCT = D(2026, 11, 1), D(2026, 10, 1)
TODAY, JUNE = D(2026, 11, 16), D(2026, 6, 1)


def pay(actor, student, amount, method, day=TODAY):
    return billing.payments.record_payment(
        actor=actor, student=student, amount=amount, method=method, paid_on=day
    )


@pytest.fixture
def ledger(clock, director, admin_a, branch_a, branch_b, monthly, cash, terminal):
    """Branch A: one student from 1 Oct (Oct + Nov charged), paid 300 000 cash in Oct and
    200 000 by card in Nov, plus a 50 000 cash payment that was reversed.
    Branch B: one student from 2 Nov, paid 100 000 cash."""
    from apps.core.roles import Role
    from tests.factories import UserFactory

    admin_b = UserFactory(role=Role.BRANCH_ADMIN, branches=[branch_b])
    group_a = make_group(admin_a, branch_a, course=monthly, start=D(2026, 9, 1), days=MWF)
    group_b = make_group(admin_b, branch_b, course=monthly, start=D(2026, 9, 1), days=MWF)
    sa = make_student(admin_a, branch_a)
    st.enroll(actor=admin_a, student=sa, group=group_a, start_date=OCT)
    sb = make_student(admin_b, branch_b)
    st.enroll(actor=admin_b, student=sb, group=group_b, start_date=D(2026, 11, 2))
    clock.move_to(dt.datetime(2026, 10, 5, 5, 0, tzinfo=dt.UTC))  # payments can't be backdated
    pay(admin_a, sa, 300_000, cash, D(2026, 10, 5))
    clock.move_to(NOW)
    pay(admin_a, sa, 200_000, terminal)
    wrong = pay(admin_a, sa, 50_000, cash)
    billing.payments.reverse_payment(actor=director, payment=wrong, reason="xato")
    pay(admin_b, sb, 100_000, cash)
    charges = {
        (c.student_id, c.period_month): net(c) for c in Charge.objects.filter(kind="monthly")
    }
    return {"a": sa, "b": sb, "charges": charges, "admin_b": admin_b}


def build(key, user, start=JUNE, end=TODAY, branch_id=None):
    return get_report(key).build(user, Params(start, end, branch_id))


class TestFinanceReports:
    def test_by_month_charged_and_collected(self, director, ledger):
        c = ledger["charges"]
        a, b = ledger["a"].pk, ledger["b"].pk
        rows = {
            r["month"]: r for r in queries.by_month(director, None, D(2026, 9, 1), D(2026, 11, 30))
        }
        assert list(rows) == [D(2026, 9, 1), OCT, NOV]
        assert rows[D(2026, 9, 1)] == {"month": D(2026, 9, 1), "charged": 0, "collected": 0}
        assert rows[OCT]["charged"] == c[(a, OCT)]
        assert rows[OCT]["collected"] == 300_000
        assert rows[NOV]["charged"] == c[(a, NOV)] + c[(b, NOV)]
        # The reversed 50 000 nets out: +50 000 payment, -50 000 reversal.
        assert rows[NOV]["collected"] == 200_000 + 100_000

    def test_report_totals_and_difference(self, director, ledger):
        result = build("oylar", director, D(2026, 10, 1), D(2026, 11, 30))
        charged = sum(ledger["charges"].values())
        assert result.totals[1:] == [charged, 600_000, 600_000 - charged]
        assert all(row[3] == row[2] - row[1] for row in result.rows)

    def test_by_method_separates_in_and_out(self, director, ledger):
        rows = {r["method"]: r for r in queries.by_method(director, None, NOV, D(2026, 11, 30))}
        assert rows["Naqd"]["in"] == 150_000 and rows["Naqd"]["out"] == 50_000
        assert rows["Naqd"]["net"] == 100_000 and rows["Naqd"]["count"] == 3
        assert rows["Terminal (karta)"]["net"] == 200_000

    def test_collected_matches_cash_report(self, admin_a, branch_a, ledger):
        today = D(2026, 11, 16)
        day = billing.cash.day_report(branch_a.pk, today)
        by_method = {r["method"]: r for r in queries.by_method(admin_a, None, today, today)}
        assert day["total_net"] == 200_000 + 50_000 - 50_000
        for line in day["methods"]:
            report = by_method.get(line["method"].name, {"in": 0, "out": 0, "net": 0})
            assert (report["in"], report["out"], report["net"]) == (
                line["in"],
                line["out"],
                line["net"],
            )
        collected = queries.collected_total(queries.payments(admin_a, None, today, today))
        assert collected == day["total_net"]

    def test_by_course_follows_allocation(self, director, monthly, ledger):
        rows = queries.by_course(director, None, OCT, D(2026, 11, 30))
        assert len(rows) == 1 and rows[0]["course"] == monthly.name
        assert rows[0]["charged"] == sum(ledger["charges"].values())
        # Every payment so far is smaller than the debt, so all of it is allocated.
        assert rows[0]["collected"] == 600_000

    def test_debt_matches_debtors_list(self, director, admin_a, ledger):
        debtors = billing_selectors.debtors(director)
        open_, overdue = queries.debt(director, None)
        assert overdue == sum(r["overdue"] for r in debtors)
        assert open_ == sum(ledger["charges"].values()) - 600_000
        result = build("qarzdorlik", director)
        assert result.totals[1:3] == [open_, overdue]
        assert result.rows[0][3] == len(debtors)


class TestBranchScope:
    def test_admin_sees_only_own_branch(self, admin_a, director, branch_a, branch_b, ledger):
        mine = build("filiallar", admin_a)
        assert [r[0] for r in mine.rows] == [branch_a.name]
        everyone = build("filiallar", director)
        assert {r[0] for r in everyone.rows} == {branch_a.name, branch_b.name}
        assert build("oylar", admin_a).totals[2] == 500_000
        assert build("oylar", ledger["admin_b"]).totals[2] == 100_000

    def test_admin_cannot_widen_scope_with_branch_filter(self, admin_a, branch_b, ledger):
        # The branch switcher only offers own branches; even a forged filter finds nothing.
        assert build("oylar", admin_a, branch_id=branch_b.pk).totals[1:3] == [0, 0]
        assert build("filiallar", admin_a, branch_id=branch_b.pk).rows == []

    def test_director_branch_filter(self, director, branch_b, ledger):
        assert build("oylar", director, branch_id=branch_b.pk).totals[2] == 100_000


class TestLeadReports:
    DATA = {"first_name": "Aziz", "last_name": "Karimov", "phone": "+998901234567"}

    def test_conversion_by_source_and_manager(self, clock, manager_a, admin_a, branch_a):
        insta, *_ = LeadSource.objects.all()
        for _i in range(3):
            make_lead(manager_a, branch_a, source=insta, manager=manager_a)
        won = make_lead(manager_a, branch_a, source=insta, manager=manager_a)
        crm.convert(actor=manager_a, lead=won, student_data={**self.DATA, "parent_phone": ""})
        result = build("lid-manbalar", admin_a, D(2026, 11, 1), D(2026, 11, 30))
        row = next(r for r in result.rows if r[0] == insta.name)
        assert row[1:3] == [4, 1] and row[4] == 0.25
        by_manager = build("lid-menejerlar", admin_a, D(2026, 11, 1), D(2026, 11, 30))
        assert by_manager.rows[0][0] == manager_a.full_name
        # Outside the period: nothing.
        assert build("lid-manbalar", admin_a, D(2026, 1, 1), D(2026, 1, 31)).rows == []


class TestScreensAndExcel:
    def test_every_report_renders_in_uzbek(self, login, director, ledger):
        client = login(director)
        for r in reports():
            text = page_text(client.get(f"/hisobotlar/{r.key}/"))
            assert str(r.title) in text
        assert "Jami" in page_text(client.get("/hisobotlar/oylar/"))

    def test_excel_headers_are_uzbek_and_money_numeric(self, login, director, ledger):
        client = login(director)
        resp = client.get("/hisobotlar/oylar/excel/?dan=01.10.2026&gacha=30.11.2026")
        ws = load_workbook(io.BytesIO(resp.content)).active
        assert [c.value for c in ws[1]] == ["Oy", "Hisoblangan", "Tushum", "Farq"]
        assert ws.cell(row=2, column=3).value == 300_000
        assert "so'm" in ws.cell(row=2, column=3).number_format
        assert ws.cell(row=ws.max_row, column=1).value == "Jami"

    @pytest.mark.parametrize(
        "url",
        ["/qarzdorlar/?excel=1", "/tolovlar/?excel=1", "/kassa/?excel=1", "/jurnal/?excel=1"],
    )
    def test_screen_exports_open_with_uzbek_headers(self, login, director, ledger, url):
        resp = login(director).get(url)
        assert resp.status_code == 200
        ws = load_workbook(io.BytesIO(resp.content)).active
        headers = [str(c.value) for c in ws[1]]
        assert headers and all(headers)
        english = {"Student", "Amount", "Date", "Method", "Branch", "Details", "Action", "User"}
        assert not english & set(headers), headers

    def test_debtors_export_matches_screen(self, login, director, ledger):
        resp = login(director).get("/qarzdorlar/?excel=1")
        ws = load_workbook(io.BytesIO(resp.content)).active
        debtors = billing_selectors.debtors(director)
        assert ws.max_row - 2 == len(debtors)  # header + rows + totals
        assert ws.cell(row=ws.max_row, column=1).value == "Jami"


class TestDashboard:
    def test_numbers(self, director, ledger):
        data = dashboard.overview(director, None)
        assert data["collected_now"] == 300_000
        assert data["charged_now"] == sum(v for (_s, m), v in ledger["charges"].items() if m == NOV)
        assert len(data["chart"]["months"]) == 6
        assert data["chart"]["ticks"][-1]["pct"] == 100
        assert all(0 <= m["charged_pct"] <= 100 for m in data["chart"]["months"])
        assert len(data["branches"]) == 2

    def test_same_days_comparison(self, director, ledger):
        # Last month up to 16.10: the 300 000 paid on 05.10.
        assert dashboard.overview(director, None)["collected_prev_same"] == 300_000

    def test_compact_axis_labels(self):
        assert dashboard._nice_max(1_234_567) == 2_000_000
        assert dashboard._nice_max(0) == 1_000_000
        assert dashboard._compact(2_500_000) == "2,5 mln"
        assert dashboard._compact(2_000_000) == "2 mln"
        assert dashboard._compact(400_000) == "400 ming"

    def test_chart_css_numbers_are_not_localized(self, login, director, ledger):
        import re

        html = login(director).get("/").content.decode()
        heights = re.findall(r"(?:height|bottom): ([^;\"]+)", html)
        assert heights and not [h for h in heights if "," in h], heights

    def test_widget_only_for_finance_roles(self, login, director, manager_a, teacher_a, ledger):
        assert "Shu oydagi tushum" in page_text(login(director).get("/"))
        for user in (manager_a, teacher_a):
            assert "Shu oydagi tushum" not in page_text(login(user).get("/"))

    def test_leads_this_month(self, clock, director, manager_a, branch_a):
        make_lead(manager_a, branch_a, follow_up_at=timezone.now())
        assert dashboard.overview(director, None)["new_leads"] == 1
