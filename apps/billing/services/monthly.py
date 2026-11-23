"""What a month should cost for an enrollment (docs/SPEC.md 6.4.2).

One engine for the monthly job, joining, leaving, freezing, unfreezing and moving:
    total    = lessons the group's schedule has in the month, minus cancelled lessons
    billable = those inside the enrollment window [start, end) and outside every freeze
    base     = price × billable / total (rounded); discounts apply on top
"""

import datetime as dt
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit, dates
from apps.core.datemath import add_months, month_start
from apps.core.system_settings import get_setting
from apps.students import selectors as student_selectors
from apps.students.models import Enrollment, Group

from .. import selectors
from ..domain import discounts as disc
from ..domain.proration import billable_lessons, prorate
from ..models import Charge, Price
from . import ledger


def month_end(month: dt.date) -> dt.date:
    return add_months(month, 1) - dt.timedelta(days=1)


def months_between(first: dt.date, last: dt.date) -> list[dt.date]:
    out, m = [], month_start(first)
    while m <= month_start(last):
        out.append(m)
        m = add_months(m, 1)
    return out


def planned_lessons(group: Group, month: dt.date) -> list[dt.date]:
    """The month's lesson dates by the weekly schedule, minus cancelled lessons."""
    return student_selectors.planned_lesson_dates(group, month, month_end(month))


def window_end(end: dt.date | None, group: Group) -> dt.date | None:
    """Enrollment end (exclusive), cut at the group's last day (inclusive)."""
    group_end = group.end_date + dt.timedelta(days=1) if group.end_date else None
    candidates = [d for d in (end, group_end) if d is not None]
    return min(candidates) if candidates else None


def monthly_price(group: Group, day: dt.date) -> Price | None:
    return selectors.effective_price(
        course_id=group.course_id,
        kind=Price.Kind.MONTHLY,
        on_date=day,
        branch_id=group.branch_id,
        group_id=group.pk,
    )


def due_date_for(month: dt.date, first_day: dt.date | None) -> dt.date:
    """First month (joining / back from freeze): due on that day. Otherwise the due day."""
    if first_day is not None and month_start(first_day) == month:
        return first_day
    return month.replace(day=get_setting("billing.monthly_due_day"))


@dataclass
class Line:
    """One suggested money change shown on the confirmation step."""

    key: str
    kind: str  # "new" | "adjust" | "cancel_part" | "error"
    month: dt.date | None = None
    group: Group | None = None
    charge: Charge | None = None
    current_net: int | None = None
    suggested: int = 0  # new: amount before discounts; adjust: target net
    base_amount: int = 0
    price: Price | None = None
    due_date: dt.date | None = None
    billable: int = 0
    total: int = 0
    discount_lines: list = field(default_factory=list)
    message: str = ""
    posted: str = ""  # what the admin typed on the confirmation step (for redisplay)

    @property
    def suggested_net(self) -> int:
        if self.kind == "new":
            return self.suggested - sum(a for _k, a in self.discount_lines)
        return self.suggested

    @property
    def delta(self) -> int:
        return self.suggested - (self.current_net or 0)


def side_lines(
    *,
    prefix: str,
    group: Group,
    enrollment: Enrollment | None,
    start: dt.date,
    end: dt.date | None,
    freezes: list[tuple[dt.date, dt.date | None]],
    from_month: dt.date,
    new_until: dt.date | None,
    first_day: dt.date | None,
    extra_rules: list[disc.Rule] = (),
) -> list[Line]:
    """Lines for one enrollment of a MONTHLY course from `from_month` on.

    Existing charges get an adjustment when their target changed. Months without a charge
    get a new charge up to `new_until` (None = never create new charges).
    """
    step = ledger.step()
    existing = {}
    if enrollment is not None:
        existing = {
            c.period_month: c
            for c in Charge.objects.filter(
                enrollment=enrollment, kind=Charge.Kind.MONTHLY, period_month__gte=from_month
            ).prefetch_related("discounts")
        }
    last = max([from_month, *existing.keys(), *([month_start(new_until)] if new_until else [])])
    window = (start, window_end(end, group))
    lines = []
    for month in months_between(from_month, last):
        total_dates = planned_lessons(group, month)
        billable = billable_lessons(total_dates, window, freezes)
        charge = existing.get(month)
        if charge is not None:
            base = prorate(charge.base_amount, billable, len(total_dates), step)
            rules = [disc.Rule(key=d, kind=d.kind, value=d.value) for d in charge.discounts.all()]
            target = disc.net(base, rules, step)
            current = ledger.net_of(charge)
            if target != current:
                lines.append(
                    Line(
                        key=f"{prefix}a{charge.pk}",
                        kind="adjust",
                        month=month,
                        group=group,
                        charge=charge,
                        current_net=current,
                        suggested=target,
                        billable=billable,
                        total=len(total_dates),
                    )
                )
            continue
        if new_until is None or month > month_start(new_until) or billable == 0:
            continue
        price_day = max(start, month)
        price = monthly_price(group, price_day)
        if price is None:
            lines.append(
                Line(
                    key=f"{prefix}e{month:%Y%m}",
                    kind="error",
                    month=month,
                    group=group,
                    message=_("The course %(course)s has no monthly price for %(day)s.")
                    % {"course": group.course.name, "day": dates.format_date(price_day)},
                )
            )
            continue
        base = prorate(price.amount, billable, len(total_dates), step)
        due = due_date_for(month, first_day)
        rules = list(extra_rules)
        if enrollment is not None:
            rules = ledger.rules_for(ledger.assignments_on(enrollment.pk, due)) + rules
        lines.append(
            Line(
                key=f"{prefix}n{month:%Y%m}",
                kind="new",
                month=month,
                group=group,
                suggested=base,
                base_amount=price.amount,
                price=price,
                due_date=due,
                billable=billable,
                total=len(total_dates),
                discount_lines=disc.lines(base, rules, step),
            )
        )
    return lines


def apply_line(line: Line, *, actor, value: int, reason: str, student, enrollment, adj_kind: str):
    """Write one confirmed line. `value` is what the admin accepted or typed."""
    if line.kind == "new":
        ledger.create_charge(
            actor=actor,
            student_id=student.pk,
            branch_id=enrollment.group.branch_id,
            kind=Charge.Kind.MONTHLY,
            due_date=line.due_date,
            base_amount=line.base_amount,
            amount=value,
            suggested_amount=line.suggested,
            override_reason=reason if value != line.suggested else "",
            enrollment=enrollment,
            period_month=line.month,
            price=line.price,
            rebuild=False,
        )
    elif line.kind == "adjust":
        ledger.adjust(
            actor=actor,
            charge=line.charge,
            delta=value - line.current_net,
            kind=adj_kind,
            suggested=line.delta,
            reason=reason if value != line.suggested else "",
            rebuild=False,
        )


# --- The monthly job -----------------------------------------------------------------------


def first_billable_month(enrollment: Enrollment) -> dt.date:
    """Imported enrollments are billed from the month after the import (owner decision)."""
    if enrollment.import_batch_id:
        imported_on = timezone.localtime(enrollment.import_batch.created_at).date()
        return add_months(month_start(imported_on), 1)
    return month_start(enrollment.start_date)


def generate_monthly_charges(month: dt.date | None = None) -> dict:
    """Create the month's charge for every enrollment active on its 1st. Idempotent.

    Runs daily from cron; a second run creates nothing. Prorates automatically when the
    month is cut short by a scheduled leave, a freeze inside the month or the group's end.
    """
    month = month_start(month or dates.today())
    created = skipped_no_price = 0
    candidates = (
        Enrollment.objects.filter(
            group__course__pricing_model="monthly",
            start_date__lte=month,
        )
        .exclude(group__status=Group.Status.FINISHED)
        .exclude(end_date__lte=month)
        .select_related("group", "group__course", "student", "import_batch")
        .prefetch_related("freezes", "group__slots")
    )
    for e in candidates:
        if Charge.objects.filter(
            enrollment=e, kind=Charge.Kind.MONTHLY, period_month=month
        ).exists():
            continue
        if first_billable_month(e) > month:
            continue
        freezes = [(f.from_date, f.to_date) for f in e.freezes.all()]
        if any(f <= month and (t is None or month < t) for f, t in freezes):
            continue  # frozen on the 1st: no charge (SPEC Q-5)
        lines = side_lines(
            prefix="",
            group=e.group,
            enrollment=e,
            start=e.start_date,
            end=e.end_date,
            freezes=freezes,
            from_month=month,
            new_until=month,
            first_day=None,
        )
        for line in lines:
            if line.kind == "error":
                skipped_no_price += 1
            elif line.kind == "new" and line.month == month:
                with transaction.atomic():
                    ledger.create_charge(
                        actor=None,
                        student_id=e.student_id,
                        branch_id=e.group.branch_id,
                        kind=Charge.Kind.MONTHLY,
                        due_date=line.due_date,
                        base_amount=line.base_amount,
                        amount=line.suggested,
                        suggested_amount=line.suggested,
                        enrollment=e,
                        period_month=month,
                        price=line.price,
                        description=_("Prorated") if line.billable < line.total else "",
                    )
                created += 1
    summary = {"month": month.isoformat(), "created": created, "no_price": skipped_no_price}
    if created or skipped_no_price:
        audit.record(None, "billing.monthly_job.run", entity_type="billing.charge", after=summary)
    return summary
