"""Installment courses: plan at enrollment, discounts on parts, leaving, editing (SPEC 6.4.3)."""

import pytest
from django.core.exceptions import ValidationError

from apps.billing import services
from apps.billing.models import Charge, InstallmentPlan, InstallmentPlanRevision
from apps.students import services as st
from tests.factories import make_group

from .helpers import MWF, D, fixed, net, percent

pytestmark = pytest.mark.django_db


@pytest.fixture
def igroup(clock, admin_a, branch_a, installment):
    return make_group(
        admin_a, branch_a, course=installment, start=D(2026, 9, 1), end=D(2027, 5, 31), days=MWF
    )


def parts(enrollment):
    return list(
        Charge.objects.filter(enrollment=enrollment, kind="installment").order_by("part_no", "id")
    )


def test_plan_created_from_template_without_proration(admin_a, student, igroup):
    e = st.enroll(actor=admin_a, student=student, group=igroup, start_date=D(2026, 11, 16))
    plan = InstallmentPlan.objects.get(enrollment=e)
    assert plan.full_price == 3_000_000
    assert [(c.part_no, c.amount, c.due_date) for c in parts(e)] == [
        (1, 1_000_000, D(2026, 11, 16)),
        (2, 1_000_000, D(2026, 12, 16)),
        (3, 1_000_000, D(2027, 1, 16)),
    ]


def test_discount_chosen_at_enrollment_applies_to_parts(admin_a, student, igroup):
    pct, promo = percent(bp=1000), fixed(amount=150_000)
    data = {"x_seen": "1", "x_discount": str(pct.pk)}
    e = st.enroll(
        actor=admin_a,
        student=student,
        group=igroup,
        start_date=D(2026, 11, 16),
        extension_data=data,
    )
    assert [net(c) for c in parts(e)] == [900_000, 900_000, 900_000]
    # A fixed discount is spread over the parts (remainder on part 1)
    from apps.billing.domain.discounts import Rule
    from apps.billing.domain.installments import Part
    from apps.billing.services.installments import part_discounts

    ps = [Part(i, 1_000_000, D(2026, 11, 16)) for i in (1, 2, 3)]
    lines = part_discounts(ps, [Rule("p", "fixed", promo.value)], 1000)
    assert [sum(a for _k, a in ln) for _p, ln in lines] == [50_000, 50_000, 50_000]


def test_custom_discount_value_is_director_only(admin_a, director, student, igroup):
    from django.core.exceptions import PermissionDenied

    dt_ = percent(bp=1000, allow_custom_value=True)
    data = {"x_seen": "1", "x_discount": str(dt_.pk), "x_discount_value": "25"}
    with pytest.raises(PermissionDenied):
        st.enroll(
            actor=admin_a,
            student=student,
            group=igroup,
            start_date=D(2026, 11, 16),
            extension_data=data,
        )
    e = st.enroll(
        actor=director,
        student=student,
        group=igroup,
        start_date=D(2026, 11, 16),
        extension_data=data,
    )
    assert [net(c) for c in parts(e)] == [750_000] * 3


def test_leaving_cancels_future_parts_by_default(admin_a, student, igroup):
    e = st.enroll(actor=admin_a, student=student, group=igroup, start_date=D(2026, 11, 16))
    st.leave(actor=admin_a, enrollment=e, end_date=D(2026, 12, 20), reason="ketdi")
    assert [net(c) for c in parts(e)] == [1_000_000, 1_000_000, 0]  # part 3 (16.01) cancelled


def test_keeping_future_parts_needs_a_reason(admin_a, student, igroup):
    e = st.enroll(actor=admin_a, student=student, group=igroup, start_date=D(2026, 11, 16))
    with pytest.raises(ValidationError):
        st.leave(
            actor=admin_a,
            enrollment=e,
            end_date=D(2026, 12, 20),
            reason="ketdi",
            extension_data={"x_seen": "1"},
        )
    st.leave(
        actor=admin_a,
        enrollment=e,
        end_date=D(2026, 12, 20),
        reason="ketdi",
        extension_data={"x_seen": "1", "x_reason": "Shartnoma bo'yicha to'liq to'lanadi"},
    )
    assert [net(c) for c in parts(e)] == [1_000_000] * 3


def test_freeze_does_not_change_the_plan(admin_a, student, igroup):
    e = st.enroll(actor=admin_a, student=student, group=igroup, start_date=D(2026, 11, 16))
    st.freeze(actor=admin_a, enrollment=e, from_date=D(2026, 11, 20), reason="kasal")
    assert [net(c) for c in parts(e)] == [1_000_000] * 3


def test_plan_edit_amount_and_date(admin_a, manager_a, student, igroup):
    e = st.enroll(actor=admin_a, student=student, group=igroup, start_date=D(2026, 11, 16))
    plan = InstallmentPlan.objects.get(enrollment=e)
    p1, p2, p3 = parts(e)
    changes = [
        {"charge": p2, "amount": 1_200_000, "due_date": p2.due_date},
        {"charge": p3, "amount": 800_000, "due_date": D(2027, 2, 1)},
    ]
    with pytest.raises(ValidationError):
        services.installments.edit_plan(actor=admin_a, plan=plan, changes=changes, reason="")
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        services.installments.edit_plan(actor=manager_a, plan=plan, changes=changes, reason="x")
    services.installments.edit_plan(
        actor=admin_a, plan=plan, changes=changes, reason="Oila iltimosi"
    )
    assert net(p2) == 1_200_000 and net(p3) == 0
    replacement = Charge.objects.get(plan=plan, part_no=3, due_date=D(2027, 2, 1))
    assert net(replacement) == 800_000
    rev = InstallmentPlanRevision.objects.get()
    assert rev.reason == "Oila iltimosi" and rev.before != rev.after
