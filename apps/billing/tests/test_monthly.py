"""Monthly courses: first-month proration, the monthly job, leave/freeze/move (SPEC 6.4.2)."""

import pytest
from django.core.exceptions import ValidationError

from apps.billing import services
from apps.billing.models import Charge, ChargeAdjustment
from apps.core.models import AuditLog
from apps.students import services as st
from apps.students.models import Enrollment
from tests.factories import make_group, make_student

from .helpers import MWF, D, monthly_charges, net, percent

pytestmark = pytest.mark.django_db
NOV, DEC = D(2026, 11, 1), D(2026, 12, 1)


def enroll(actor, student, group, day, data=None):
    return st.enroll(actor=actor, student=student, group=group, start_date=day, extension_data=data)


class TestJoin:
    def test_mid_month_join_is_prorated_by_lessons_left(self, admin_a, student, group):
        e = enroll(admin_a, student, group, D(2026, 11, 16))
        charge = monthly_charges(e)[NOV]
        # 7 of 13 November lessons from the 16th: 450 000 × 7/13 = 242 307 -> 242 000
        assert (charge.suggested_amount, charge.amount, charge.base_amount) == (
            242_000,
            242_000,
            450_000,
        )
        assert charge.due_date == D(2026, 11, 16)  # first month is due on the start date
        assert net(charge) == 242_000

    def test_join_before_first_lesson_is_full_month(self, admin_a, student, group):
        e = enroll(admin_a, student, group, D(2026, 11, 1))
        assert monthly_charges(e)[NOV].amount == 450_000

    def test_backdated_join_charges_every_month_up_to_now(self, admin_a, student, group):
        e = enroll(admin_a, student, group, D(2026, 10, 14))
        charges = monthly_charges(e)
        assert sorted(charges) == [D(2026, 10, 1), NOV]
        assert charges[NOV].amount == 450_000 and charges[NOV].due_date == D(2026, 11, 10)
        assert charges[D(2026, 10, 1)].amount < 450_000  # prorated October

    def test_override_needs_reason_and_keeps_both_amounts(self, admin_a, student, group):
        data = {"x_seen": "1", "x_nn202611": "300 000", "x_reason": ""}
        with pytest.raises(ValidationError):
            enroll(admin_a, student, group, D(2026, 11, 16), data)
        assert not Enrollment.objects.exists()  # the whole action rolled back
        data["x_reason"] = "Kelishilgan narx"
        e = enroll(admin_a, student, group, D(2026, 11, 16), data)
        charge = monthly_charges(e)[NOV]
        assert (charge.suggested_amount, charge.amount) == (242_000, 300_000)
        assert charge.override_reason == "Kelishilgan narx"
        assert AuditLog.objects.filter(
            action="billing.charge.create", reason="Kelishilgan narx"
        ).exists()

    def test_enroll_blocked_without_price(self, admin_a, branch_a, student, clock):
        from tests.factories import CourseFactory

        g = make_group(admin_a, branch_a, course=CourseFactory(), start=D(2026, 9, 1), days=MWF)
        with pytest.raises(ValidationError):
            enroll(admin_a, student, g, D(2026, 11, 16))
        assert not Enrollment.objects.exists()

    def test_cancelled_lesson_does_not_count(self, admin_a, student, group):
        lesson = group.lessons.get(date=D(2026, 11, 30))
        st.cancel_lesson(actor=admin_a, lesson=lesson, reason="Bayram")
        e = enroll(admin_a, student, group, D(2026, 11, 16))
        # 6 of 12 lessons now: exactly half
        assert monthly_charges(e)[NOV].amount == 225_000


class TestMonthlyJob:
    def test_generates_once_full_month_with_due_day(self, admin_a, student, group, clock):
        e = enroll(admin_a, student, group, D(2026, 11, 16))
        clock.move_to("2026-12-01 01:00+05:00")
        first = services.monthly.generate_monthly_charges()
        again = services.monthly.generate_monthly_charges()
        dec = monthly_charges(e)[DEC]
        assert first["created"] == 1 and again["created"] == 0  # idempotent
        assert dec.amount == 450_000 and dec.due_date == D(2026, 12, 10) and dec.created_by is None

    def test_price_change_applies_to_new_months_only(
        self, director, admin_a, student, group, monthly, clock
    ):
        e = enroll(admin_a, student, group, D(2026, 11, 2))
        services.add_price(
            actor=director, course=monthly, branch=None, amount=500_000, effective_from=DEC
        )
        clock.move_to("2026-12-01 09:00+05:00")
        services.monthly.generate_monthly_charges()
        charges = monthly_charges(e)
        assert charges[NOV].amount == 450_000  # issued charges never change
        assert charges[DEC].amount == 500_000 and charges[DEC].base_amount == 500_000

    def test_frozen_on_the_first_gets_no_charge(self, admin_a, student, group, clock):
        e = enroll(admin_a, student, group, D(2026, 11, 2))
        st.freeze(actor=admin_a, enrollment=e, from_date=D(2026, 11, 30), reason="kasal")
        clock.move_to("2026-12-01 09:00+05:00")
        assert services.monthly.generate_monthly_charges()["created"] == 0

    def test_scheduled_leave_and_group_end_prorate_automatically(
        self, admin_a, branch_a, monthly, clock
    ):
        g = make_group(
            admin_a, branch_a, course=monthly, start=D(2026, 9, 1), end=D(2026, 12, 15), days=MWF
        )
        s = make_student(admin_a, branch_a)
        e = enroll(admin_a, s, g, D(2026, 11, 2))
        clock.move_to("2026-12-01 09:00+05:00")
        services.monthly.generate_monthly_charges()
        dec = monthly_charges(e)[DEC]
        # December 2026 MWF: 13 lessons; the group's last day is 15.12 -> 2, 4, 7, 9, 11, 14
        # = 6 lessons: 450 000 × 6/13 = 207 692 -> 208 000
        assert dec.amount == 208_000 and dec.description

    def test_imported_enrollment_billed_from_next_month(self, admin_a, branch_a, group, clock):
        from apps.students.models import ImportBatch

        batch = ImportBatch.objects.create(
            kind="students", file_name="x.xlsx", uploaded_by=admin_a, status="committed"
        )
        s = make_student(admin_a, branch_a)
        e = st.enroll(
            actor=admin_a,
            student=s,
            group=group,
            start_date=D(2026, 9, 1),
            skip_extensions=True,
            import_batch=batch,
        )
        assert services.monthly.generate_monthly_charges(NOV)["created"] == 0  # import month
        clock.move_to("2026-12-01 09:00+05:00")
        services.monthly.generate_monthly_charges()
        assert sorted(monthly_charges(e)) == [DEC]

    def test_discounts_are_separate_lines(self, admin_a, student, group, clock):
        e = enroll(admin_a, student, group, D(2026, 11, 2))
        services.discounts.assign(
            actor=admin_a, enrollment=e, discount_type=percent(), valid_from=D(2026, 12, 1)
        )
        nov = monthly_charges(e)[NOV]
        clock.move_to("2026-12-01 09:00+05:00")
        services.monthly.generate_monthly_charges()
        dec = monthly_charges(e)[DEC]
        assert [(d.name_snapshot, d.amount) for d in dec.discounts.all()] == [("Aka-uka", 45_000)]
        assert net(dec) == 405_000
        assert net(nov) == 450_000  # the earlier charge did not change


class TestLifecycle:
    def test_leave_mid_month_suggests_reduction(self, admin_a, student, group):
        e = enroll(admin_a, student, group, D(2026, 11, 2))
        st.leave(actor=admin_a, enrollment=e, end_date=D(2026, 11, 9), reason="ko'chdi")
        nov = monthly_charges(e)[NOV]
        # 2, 4, 6 attended: 3/13 -> 103 846 -> 104 000
        assert net(nov) == 104_000
        adj = ChargeAdjustment.objects.get(charge=nov)
        assert (
            adj.kind == "proration_leave"
            and adj.amount == -346_000
            and adj.suggested_amount == -346_000
        )

    def test_leave_override_to_no_reduction_needs_reason(self, admin_a, student, group):
        e = enroll(admin_a, student, group, D(2026, 11, 2))
        key = f"x_oa{monthly_charges(e)[NOV].pk}"
        with pytest.raises(ValidationError):
            st.leave(
                actor=admin_a,
                enrollment=e,
                end_date=D(2026, 11, 9),
                reason="x",
                extension_data={"x_seen": "1", key: "450 000"},
            )
        e.refresh_from_db()
        assert e.status == "active"  # rolled back
        st.leave(
            actor=admin_a,
            enrollment=e,
            end_date=D(2026, 11, 9),
            reason="x",
            extension_data={"x_seen": "1", key: "450 000", "x_reason": "Oy to'liq to'lanadi"},
        )
        assert net(monthly_charges(e)[NOV]) == 450_000
        assert not ChargeAdjustment.objects.exists()

    def test_backdated_leave_cancels_already_generated_month(self, admin_a, student, group, clock):
        e = enroll(admin_a, student, group, D(2026, 11, 2))
        clock.move_to("2026-12-02 09:00+05:00")
        services.monthly.generate_monthly_charges()
        st.leave(actor=admin_a, enrollment=e, end_date=D(2026, 11, 30), reason="x")
        charges = monthly_charges(e)
        assert net(charges[DEC]) == 0
        assert net(charges[NOV]) == 415_000  # 12/13

    def test_freeze_and_unfreeze(self, admin_a, student, group, clock):
        e = enroll(admin_a, student, group, D(2026, 11, 2))
        st.freeze(actor=admin_a, enrollment=e, from_date=D(2026, 11, 23), reason="kasal")
        assert net(monthly_charges(e)[NOV]) == 312_000  # 9/13 -> 311 538
        clock.move_to("2026-12-01 09:00+05:00")
        services.monthly.generate_monthly_charges()
        assert DEC not in monthly_charges(e)
        clock.move_to("2026-12-14 09:00+05:00")
        st.unfreeze(actor=admin_a, enrollment=e, effective_date=D(2026, 12, 14), reason="sog'aydi")
        dec = monthly_charges(e)[DEC]
        assert dec.due_date == D(2026, 12, 14) and dec.amount == 277_000  # 8/13 -> 276 923

    def test_move_same_course_same_price_keeps_the_month(
        self, admin_a, branch_a, student, group, monthly
    ):
        e = enroll(admin_a, student, group, D(2026, 11, 2))
        other = make_group(admin_a, branch_a, course=monthly, start=D(2026, 9, 1), days=(2, 4))
        new = st.move(
            actor=admin_a,
            enrollment=e,
            target_group=other,
            effective_date=D(2026, 11, 17),
            reason="vaqt",
        )
        assert net(monthly_charges(e)[NOV]) == 450_000
        assert monthly_charges(new) == {}
        assert not ChargeAdjustment.objects.exists()

    def test_move_to_other_course_prorates_both(self, director, admin_a, branch_a, student, group):
        from tests.factories import CourseFactory

        olymp = CourseFactory(name="Olimpiada")
        services.add_price(
            actor=director, course=olymp, branch=None, amount=650_000, effective_from=D(2026, 1, 1)
        )
        other = make_group(admin_a, branch_a, course=olymp, start=D(2026, 9, 1), days=MWF)
        e = enroll(admin_a, student, group, D(2026, 11, 2))
        new = st.move(
            actor=admin_a,
            enrollment=e,
            target_group=other,
            effective_date=D(2026, 11, 16),
            reason="daraja",
        )
        assert net(monthly_charges(e)[NOV]) == 208_000  # 6/13 of 450 000
        assert monthly_charges(new)[NOV].amount == 350_000  # 7/13 of 650 000

    def test_teacher_cannot_trigger_billing(self, teacher_a, student, group):
        from django.core.exceptions import PermissionDenied

        with pytest.raises(PermissionDenied):
            enroll(teacher_a, student, group, D(2026, 11, 2))
        assert not Charge.objects.exists()


def test_management_commands(admin_a, student, group, clock):
    from io import StringIO

    from django.core.management import call_command

    enroll(admin_a, student, group, D(2026, 11, 2))
    out = StringIO()
    call_command("generate_monthly_charges", "--month", "2026-12", stdout=out)
    assert "created 1" in out.getvalue()
    out = StringIO()
    call_command("generate_lessons", stdout=out)
    assert "lessons created" in out.getvalue()
