import datetime as dt

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, InternalError, connection, transaction

from apps.billing import selectors, services
from apps.billing.models import Price
from apps.core.models import AuditLog
from tests.factories import CourseFactory

D = dt.date


@pytest.fixture
def course(db):
    return CourseFactory(name="Matematika 7-9")


@pytest.mark.django_db
class TestPriceHistory:
    def add(self, actor, course, amount, when, branch=None):
        return services.add_price(
            actor=actor, course=course, branch=branch, amount=amount, effective_from=when
        )

    def test_latest_effective_price_on_date(self, director, course):
        self.add(director, course, 400_000, D(2026, 1, 1))
        self.add(director, course, 450_000, D(2026, 9, 1))

        def price(d):
            p = selectors.effective_price(
                course_id=course.id, kind="monthly", on_date=d, branch_id=None
            )
            return p.amount

        assert price(D(2026, 8, 31)) == 400_000
        assert price(D(2026, 9, 1)) == 450_000
        assert (
            selectors.effective_price(
                course_id=course.id, kind="monthly", on_date=D(2025, 12, 31), branch_id=None
            )
            is None
        )

    def test_future_price_does_not_apply_yet(self, director, course):
        self.add(director, course, 400_000, D(2026, 1, 1))
        self.add(director, course, 500_000, D(2027, 1, 1))
        p = selectors.effective_price(
            course_id=course.id, kind="monthly", on_date=D(2026, 12, 31), branch_id=None
        )
        assert p.amount == 400_000

    def test_branch_override_wins_over_general(self, director, course, branch_a, branch_b):
        self.add(director, course, 400_000, D(2026, 1, 1))
        self.add(director, course, 380_000, D(2026, 1, 1), branch=branch_b)
        self.add(director, course, 450_000, D(2026, 6, 1))

        def get(b):
            p = selectors.effective_price(
                course_id=course.id, kind="monthly", on_date=D(2026, 7, 1), branch_id=b
            )
            return p.amount

        assert get(branch_a.pk) == 450_000
        assert get(branch_b.pk) == 380_000

    def test_kind_follows_course_pricing_model(self, director):
        inst = CourseFactory(pricing_model="installment")
        price = self.add(director, inst, 3_000_000, D(2026, 1, 1))
        assert price.kind == Price.Kind.FULL_COURSE

    def test_price_change_is_audited(self, director, course):
        price = self.add(director, course, 400_000, D(2026, 1, 1))
        entry = AuditLog.objects.get(action="billing.price.create")
        assert entry.entity_id == str(price.pk)
        assert entry.after["amount"] == 400_000
        assert entry.actor == director

    def test_only_director_can_add_prices(self, admin_a, course):
        with pytest.raises(PermissionDenied):
            self.add(admin_a, course, 400_000, D(2026, 1, 1))

    @pytest.mark.parametrize(
        "sql", ["UPDATE billing_price SET amount = 1", "DELETE FROM billing_price"]
    )
    def test_price_rows_are_immutable(self, director, course, sql):
        self.add(director, course, 400_000, D(2026, 1, 1))
        with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(sql)
        assert Price.objects.get().amount == 400_000

    def test_amount_must_be_positive(self, director, course):
        with pytest.raises(Exception):  # noqa: B017 - service or DB constraint
            self.add(director, course, 0, D(2026, 1, 1))


@pytest.mark.django_db
def test_group_price_wins_over_branch_and_general(director, branch_a, course):
    from tests.factories import make_group

    group = make_group(director, branch_a, course=course)
    other_group = make_group(director, branch_a, course=course)
    for branch, grp, amount in (
        (None, None, 400_000),
        (branch_a, None, 420_000),
        (None, group, 350_000),
    ):
        services.add_price(
            actor=director,
            course=course,
            branch=branch,
            group=grp,
            amount=amount,
            effective_from=D(2026, 1, 1),
        )

    def price(group_id):
        return selectors.effective_price(
            course_id=course.id,
            kind="monthly",
            on_date=D(2026, 7, 1),
            branch_id=branch_a.pk,
            group_id=group_id,
        ).amount

    assert price(group.pk) == 350_000
    assert price(other_group.pk) == 420_000  # branch price, not the other group's
    assert Price.objects.get(group=group).branch == branch_a  # branch filled from the group


@pytest.mark.django_db
def test_group_must_match_course(director, branch_a, course):
    from django.core.exceptions import ValidationError

    from tests.factories import make_group

    group = make_group(director, branch_a)  # a different course
    with pytest.raises(ValidationError):
        services.add_price(
            actor=director,
            course=course,
            branch=None,
            group=group,
            amount=1,
            effective_from=D(2026, 1, 1),
        )
