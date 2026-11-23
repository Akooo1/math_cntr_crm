"""Morning check-in end to end (docs/SPEC.md §14). Clock: Monday 16.11.2026, Tashkent."""

import datetime as dt

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.core import outbox
from apps.core.models import AuditLog, OutboxEvent
from apps.core.reports import Params, get_report
from apps.staff import selectors, services
from apps.staff.models import BranchLocation, CheckIn, Schedule
from tests.factories import page_text

pytestmark = pytest.mark.django_db

HERE = (41.2756, 69.2034)  # the branch
NEAR = (41.2765, 69.2034)  # about 100 m away
FAR = (41.2900, 69.2034)  # about 1.6 km away
MON = dt.date(2026, 11, 16)


def at(clock, hh, mm, day=MON):
    """Move the frozen clock to hh:mm Tashkent (UTC+5) on `day`."""
    clock.move_to(dt.datetime(day.year, day.month, day.day, hh - 5, mm, tzinfo=dt.UTC))


@pytest.fixture
def place(clock, director, branch_a):
    services.save_location(
        actor=director, branch=branch_a, latitude=HERE[0], longitude=HERE[1], radius_m=200
    )
    return branch_a


@pytest.fixture
def nine(place, director, teacher_a):
    services.save_schedule(
        actor=director, user=teacher_a, start_time=dt.time(9, 0), workdays=[1, 2, 3, 4, 5, 6]
    )
    return teacher_a


def check(user, coords=NEAR, accuracy=20):
    return services.check_in(
        actor=user, latitude=coords[0], longitude=coords[1], accuracy_m=accuracy
    )


class TestCheckIn:
    def test_on_time(self, clock, nine, place):
        at(clock, 8, 55)
        c = check(nine)
        assert (c.branch, c.date, c.late_minutes, c.source) == (place, MON, 0, "gps")
        assert c.expected_start == dt.time(9, 0) and 80 <= c.distance_m <= 120
        event = OutboxEvent.objects.get(event_type="staff.checked_in")
        assert event.payload["time"] == "08:55" and event.payload["late_minutes"] == 0
        assert AuditLog.objects.filter(action="staff.checkin.create").exists()

    def test_late_after_grace(self, clock, nine):
        at(clock, 9, 10)
        assert check(nine).late_minutes == 0  # 10 minutes of grace
        at(clock, 9, 25, MON + dt.timedelta(days=1))
        assert check(nine).late_minutes == 25

    def test_refusals(self, clock, nine, teacher_a, director):
        at(clock, 8, 50)
        with pytest.raises(ValidationError, match="1"):
            check(nine, FAR)  # "You are 1 6xx m from ..."
        with pytest.raises(ValidationError):
            check(nine, accuracy=500)
        with pytest.raises(ValidationError):
            check(nine, accuracy=None)
        check(nine)
        with pytest.raises(ValidationError):
            check(nine)  # once a day
        with pytest.raises(PermissionDenied):
            check(director)

    def test_branch_without_location(self, clock, manager_a):
        with pytest.raises(ValidationError):
            check(manager_a)

    def test_no_schedule_never_late(self, clock, place, manager_a):
        at(clock, 14, 0)
        assert check(manager_a).late_minutes == 0

    def test_day_off_not_late(self, clock, nine):
        at(clock, 15, 0, dt.date(2026, 11, 22))  # Sunday, not a workday
        c = check(nine)
        assert c.late_minutes == 0 and c.expected_start is None

    def test_append_only(self, clock, nine):
        check(nine)
        with pytest.raises(IntegrityError), transaction.atomic():
            CheckIn.objects.update(late_minutes=0)
        with pytest.raises(IntegrityError), transaction.atomic():
            CheckIn.objects.all().delete()


class TestManual:
    def test_director_records_by_hand(self, clock, nine, place, director):
        c = services.manual_check_in(
            actor=director,
            user=nine,
            branch=place,
            day=MON,
            time=dt.time(9, 30),
            reason="telefon o'chgan",
        )
        assert (c.source, c.late_minutes, c.distance_m) == ("manual", 30, None)

    def test_rules(self, clock, nine, place, director, branch_b, admin_a):
        args = {"actor": director, "user": nine, "day": MON, "reason": "x"}
        with pytest.raises(ValidationError):  # future
            services.manual_check_in(branch=place, time=dt.time(11, 0), **args)
        with pytest.raises(ValidationError):  # not their branch
            services.manual_check_in(branch=branch_b, time=dt.time(9, 0), **args)
        with pytest.raises(ValidationError):
            services.manual_check_in(branch=place, time=dt.time(9, 0), **{**args, "reason": " "})
        with pytest.raises(PermissionDenied):
            services.manual_check_in(branch=place, time=dt.time(9, 0), **{**args, "actor": admin_a})


class TestBoardAndReport:
    def test_board(self, clock, nine, place, director, admin_a, manager_a):
        services.save_schedule(
            actor=director, user=manager_a, start_time=dt.time(9, 0), workdays=[1]
        )
        services.save_schedule(actor=director, user=admin_a, start_time=dt.time(9, 0), workdays=[7])
        at(clock, 9, 40)
        check(nine)
        rows = {r["user"]: r["status"] for r in selectors.board(director, MON)["rows"]}
        assert rows[nine] == "late"
        assert rows[manager_a] == "not_yet"
        assert rows[admin_a] == "day_off"
        at(clock, 9, 0, MON + dt.timedelta(days=1))
        yesterday = {r["user"]: r["status"] for r in selectors.board(director, MON)["rows"]}
        assert yesterday[manager_a] == "absent"
        with pytest.raises(PermissionDenied):
            selectors.board(admin_a, MON)

    def test_monthly_report(self, clock, nine, director):
        at(clock, 9, 30, dt.date(2026, 11, 2))  # Monday, late 30
        check(nine)
        at(clock, 8, 50, dt.date(2026, 11, 3))
        check(nine)
        at(clock, 10, 0)  # 16.11
        result = get_report("xodimlar-davomati").build(
            director, Params(dt.date(2026, 11, 1), dt.date(2026, 11, 30), None)
        )
        row = next(r for r in result.rows if r[0] == nine.full_name)
        # Workdays Mon–Sat from 1.11 to 15.11: 12. Came 2, late once, 30 minutes, missed 10.
        assert row[2:] == [12, 2, 1, 30, 10]


class TestScreens:
    def test_keldim_button_and_post(self, clock, nine, login):
        at(clock, 8, 58)
        client = login(nine)
        assert "Keldim" in page_text(client.get("/"))
        client.post("/keldim/", {"lat": str(NEAR[0]), "lng": str(NEAR[1]), "accuracy": "15"})
        assert CheckIn.objects.filter(user=nine, late_minutes=0).exists()
        assert "08:58" in page_text(client.get("/"))
        resp = client.post("/keldim/", {"lat": "", "lng": ""}, follow=True)
        assert resp.status_code == 200

    def test_director_pages(self, clock, nine, place, login, director):
        client = login(director)
        at(clock, 9, 5)
        assert nine.full_name in page_text(client.get("/xodimlar-davomati/"))
        assert "Keldim" not in page_text(client.get("/"))  # the Direktor doesn't check in
        resp = client.post(
            f"/sozlamalar/filial-joylashuvi/{place.pk}/",
            {"coordinates": "41,3, 69,2", "radius_m": "150"},
        )
        assert resp.status_code == 302
        loc = BranchLocation.objects.get(branch=place)
        assert (loc.latitude, loc.longitude, loc.radius_m) == (41.3, 69.2, 150)
        resp = client.post(
            f"/sozlamalar/ish-vaqti/{nine.pk}/",
            {"start_time": "08:30", "workdays": ["1", "3", "5"]},
        )
        assert resp.status_code == 302
        assert Schedule.objects.get(user=nine).start_time == dt.time(8, 30)
        assert "08:30" in page_text(client.get("/sozlamalar/ish-vaqti/"))


class TestOutbox:
    def test_manual_purge(self, clock, director, admin_a, nine):
        at(clock, 8, 0)
        check(nine)
        OutboxEvent.objects.create(event_type="old", payload={})
        OutboxEvent.objects.filter(event_type="old").update(
            occurred_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        )
        assert outbox.stats()["by_age"][90] == 1
        with pytest.raises(PermissionDenied):
            outbox.purge(actor=admin_a, older_than_days=90)
        assert outbox.purge(actor=director, older_than_days=90) == 1
        assert OutboxEvent.objects.filter(event_type="staff.checked_in").exists()
        assert AuditLog.objects.filter(action="core.outbox.purge").exists()
