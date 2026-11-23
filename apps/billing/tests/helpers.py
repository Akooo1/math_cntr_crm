"""Shared setup for billing tests. Clock: Monday 16.11.2026 10:00 Tashkent."""

import datetime as dt

import pytest
import time_machine

from apps.billing import services
from apps.billing.models import Charge, ChargeNet, DiscountType, InstallmentTemplate, PaymentMethod
from apps.settings.models import Course
from tests.factories import CourseFactory, make_group, make_student

D = dt.date
NOW = dt.datetime(2026, 11, 16, 5, 0, tzinfo=dt.UTC)  # 10:00 in Tashkent
MWF = (1, 3, 5)  # November 2026 has 13 Mon/Wed/Fri lessons


@pytest.fixture
def clock():
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture
def monthly(director):
    course = CourseFactory(name="Matematika 7", pricing_model=Course.PricingModel.MONTHLY)
    services.add_price(
        actor=director, course=course, branch=None, amount=450_000, effective_from=D(2026, 1, 1)
    )
    return course


@pytest.fixture
def installment(director):
    course = CourseFactory(name="DTM", pricing_model=Course.PricingModel.INSTALLMENT)
    services.add_price(
        actor=director, course=course, branch=None, amount=3_000_000, effective_from=D(2026, 1, 1)
    )
    InstallmentTemplate.objects.create(name="3 qism", parts_count=3, course=course)
    return course


@pytest.fixture
def group(clock, admin_a, branch_a, monthly):
    return make_group(admin_a, branch_a, course=monthly, start=D(2026, 9, 1), days=MWF, capacity=30)


@pytest.fixture
def student(admin_a, branch_a):
    return make_student(admin_a, branch_a)


@pytest.fixture
def cash():
    return PaymentMethod.objects.get(name="Naqd")


@pytest.fixture
def terminal():
    return PaymentMethod.objects.get(name="Terminal (karta)")


def percent(name="Aka-uka", bp=1000, **kw):
    return DiscountType.objects.create(name=name, kind="percent", value=bp, **kw)


def fixed(name="Promo", amount=50_000, **kw):
    return DiscountType.objects.create(name=name, kind="fixed", value=amount, **kw)


def net(charge) -> int:
    return ChargeNet.objects.get(pk=charge.pk).net


def monthly_charges(enrollment):
    return {c.period_month: c for c in Charge.objects.filter(enrollment=enrollment, kind="monthly")}
