from apps.billing.models import Charge
from apps.store import selectors
from apps.store.models import Sale
from apps.students import services as student_services

from .factories import TODAY


class TestSellScreen:
    def test_tiles_and_basket_post(self, shop, admin_a, branch_a, cash, login):
        c = login(admin_a)
        page = c.get("/savdo/").content.decode()
        assert "0,5 L suv" in page and "1 L suv" in page
        assert "Algebra 7" not in page  # books are given from the student card only
        resp = c.post(
            "/savdo/",
            {
                "filial": branch_a.pk,
                f"q_{shop['small'].pk}": "3",
                f"q_{shop['big'].pk}": "0",
                "method": cash.pk,
            },
        )
        assert resp.status_code == 302
        sale = Sale.objects.get()
        assert sale.total == 9_000 and sale.method == cash
        page = c.get("/savdo/").content.decode()
        assert "0,5 L suv × 3" in page  # today's sales

    def test_errors_are_shown_and_nothing_sold(self, shop, admin_a, branch_a, cash, login):
        c = login(admin_a)
        resp = c.post(
            "/savdo/",
            {"filial": branch_a.pk, f"q_{shop['big'].pk}": "9", "method": cash.pk},
            follow=True,
        )
        assert "yetarli emas" in resp.content.decode()
        assert not Sale.objects.exists()

    def test_director_picks_a_branch_first(self, shop, director, branch_a, branch_b, login):
        page = login(director).get("/savdo/").content.decode()
        assert "Filialni tanlang" in page
        assert f"?filial={branch_b.pk}" in page


class TestBooksScreens:
    def test_panel_on_student_card(self, shop, admin_a, manager_a, student, login):
        c = login(admin_a)
        assert "Kitob berish" in c.get(f"/oquvchilar/{student.pk}/").content.decode()
        c = login(manager_a)
        assert "Kitob berish" not in c.get(f"/oquvchilar/{student.pk}/").content.decode()

    def test_give_later_then_pay_now(self, shop, admin_a, student, cash, login):
        c = login(admin_a)
        url = f"/kitob-berish/{student.pk}/"
        assert (
            c.post(url, {"book": shop["book"].pk, "quantity": "2", "pay": "later"}).status_code
            == 302
        )
        charge = Charge.objects.get(student=student)
        assert charge.amount == 120_000
        resp = c.post(
            url, {"book": shop["book"].pk, "quantity": "1", "pay": "now", "method": cash.pk}
        )
        assert resp.status_code == 302
        assert Charge.objects.filter(student=student).count() == 1
        page = c.get(f"/oquvchilar/{student.pk}/").content.decode()
        assert "To'lanmagan" in page and "Hozir to'langan" in page

    def test_give_errors_stay_on_the_form(self, shop, admin_a, student, login):
        resp = login(admin_a).post(
            f"/kitob-berish/{student.pk}/",
            {"book": shop["book"].pk, "quantity": "50", "pay": "later"},
        )
        assert resp.status_code == 200
        assert "yetarli emas" in resp.content.decode()

    def test_group_form(self, shop, admin_a, branch_a, group, student, login):
        student_services.enroll(actor=admin_a, student=student, group=group, start_date=TODAY)
        c = login(admin_a)
        page = c.get(f"/guruhga-kitob/?guruh={group.pk}").content.decode()
        assert student.full_name in page
        resp = c.post(
            "/guruhga-kitob/", {"guruh": group.pk, "book": shop["book"].pk, "student": [student.pk]}
        )
        assert resp.status_code == 302
        assert Sale.objects.get().student == student


class TestStockScreens:
    def test_stock_page_flags_low(self, shop, admin_a, director, branch_a, cash, login):
        from apps.store import services

        services.sell_items(actor=admin_a, branch=branch_a, lines=[(shop["big"], 3)], method=cash)
        page = login(admin_a).get("/ombor/").content.decode()
        assert "Kam qoldi" in page  # 2 left, threshold 3

    def test_receive_and_correct_forms(self, shop, director, branch_a, login):
        c = login(director)
        resp = c.post(
            "/ombor/kirim/",
            {
                "filial": branch_a.pk,
                "product": shop["small"].pk,
                "quantity": "10",
                "received_on": "16.11.2026",
                "purchase_cost": "25 000",
            },
        )
        assert resp.status_code == 302
        resp = c.post(
            "/ombor/tuzatish/",
            {
                "filial": branch_a.pk,
                "product": shop["small"].pk,
                "counted": "29",
                "reason": "sanoq",
            },
        )
        assert resp.status_code == 302
        assert selectors.on_hand_map(branch_a.pk)[shop["small"].pk] == 29

    def test_dashboard_low_stock_widget(self, shop, admin_a, branch_a, cash, login):
        from apps.store import services

        services.sell_items(actor=admin_a, branch=branch_a, lines=[(shop["big"], 4)], method=cash)
        assert "Kam qoldi" in login(admin_a).get("/").content.decode()


class TestReport:
    def test_numbers_and_cost_for_director_only(
        self, shop, admin_a, director, branch_a, cash, student, login
    ):
        from apps.core.reports import Params
        from apps.store import services

        services.sell_items(actor=admin_a, branch=branch_a, lines=[(shop["small"], 5)], method=cash)
        services.give_book(actor=admin_a, student=student, product=shop["book"], quantity=2)
        p = Params(TODAY, TODAY, None)
        res = selectors.stock_report(director, p)
        rows = {r[0]: r for r in res.rows}
        # small: received 20 (cost 40 000 -> 2 000 a unit), sold 5 -> cost 10 000, margin 5 000
        assert rows["0,5 L suv"][2:9] == [20, 5, 15, 15_000, 0, 10_000, 5_000]
        # book: 10 for 400 000 -> 40 000 a unit; 2 given on account at 60 000
        assert rows["Algebra 7"][2:9] == [10, 2, 8, 120_000, 120_000, 80_000, 40_000]
        # big water came without a cost: no margin rather than a wrong one
        assert rows["1 L suv"][7:9] == [None, None]
        assert res.totals[7] is None
        admin_res = selectors.stock_report(admin_a, p)
        assert len(admin_res.columns) == len(res.columns) - 2  # no cost, no margin

        c = login(director)
        assert c.get("/hisobotlar/ombor-savdo/?dan=16.11.2026&gacha=16.11.2026").status_code == 200
        resp = c.get("/hisobotlar/ombor-savdo/excel/?dan=16.11.2026&gacha=16.11.2026")
        assert resp.status_code == 200

    def test_reversals_net_out(self, shop, admin_a, director, branch_a, cash):
        from apps.core.reports import Params
        from apps.store import services

        sale = services.sell_items(
            actor=admin_a, branch=branch_a, lines=[(shop["small"], 5)], method=cash
        )
        services.reverse_sale(actor=director, sale=sale, reason="x")
        rows = {r[0]: r for r in selectors.stock_report(director, Params(TODAY, TODAY, None)).rows}
        assert rows["0,5 L suv"][3] == 0 and rows["0,5 L suv"][5] == 0


def test_missing_cost_shows_a_dash(shop, director, login):
    page = login(director).get("/hisobotlar/ombor-savdo/?dan=16.11.2026&gacha=16.11.2026")
    assert "—" in page.content.decode()
