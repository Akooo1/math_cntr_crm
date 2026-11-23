"""Installment plans (docs/SPEC.md 6.4.3)."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.permissions import ensure_branch_access, require_perm
from apps.students.models import Enrollment, Group

from .. import selectors
from ..domain import discounts as disc
from ..domain.installments import Part, build_schedule
from ..models import Charge, InstallmentPlan, InstallmentPlanRevision, InstallmentTemplate, Price
from . import ledger
from .allocation import rebuild_for_student


def templates_for(group: Group) -> list[InstallmentTemplate]:
    """The group's default first, then the course's own templates, then general ones."""
    qs = InstallmentTemplate.objects.filter(is_active=True).filter(
        Q(course=group.course) | Q(course__isnull=True)
    )
    items = sorted(qs, key=lambda t: (t.course_id is None, t.name))
    default = group.default_installment_template
    if default is not None and default.is_active:
        items = [default] + [t for t in items if t.pk != default.pk]
    return items


def course_price(group: Group, day: dt.date) -> Price | None:
    return selectors.effective_price(
        course_id=group.course_id,
        kind=Price.Kind.FULL_COURSE,
        on_date=day,
        branch_id=group.branch_id,
        group_id=group.pk,
    )


def preview(group: Group, template: InstallmentTemplate, start: dt.date, rules: list[disc.Rule]):
    """[(Part, [(rule_key, discount)], net)] for the schedule this template would create."""
    price = course_price(group, start)
    if price is None:
        return None, []
    step = ledger.step()
    parts = build_schedule(selectors.rule_for(template), price.amount, start, step)
    return price, [
        (p, d, p.amount - sum(a for _k, a in d)) for p, d in part_discounts(parts, rules, step)
    ]


def part_discounts(parts: list[Part], rules: list[disc.Rule], step: int):
    """Percent discounts apply to each part; a fixed discount reduces the course total and is
    spread over the parts (SPEC 6.4.4)."""
    fixed = [r for r in rules if r.kind == "fixed"]
    percent = [r for r in rules if r.kind == "percent"]
    spreads = {r.key: disc.spread(r.value, [p.amount for p in parts], step) for r in fixed}
    out = []
    for i, part in enumerate(parts):
        lines = disc.lines(part.amount, percent, step)
        remaining = part.amount - sum(a for _k, a in lines)
        for r in fixed:
            amount = min(spreads[r.key][i], remaining)
            remaining -= amount
            lines.append((r.key, amount))
        out.append((part, lines))
    return out


def create_plan(*, actor, enrollment: Enrollment, template: InstallmentTemplate) -> InstallmentPlan:
    group = enrollment.group
    price = course_price(group, enrollment.start_date)
    if price is None:
        raise ValidationError(
            _("The course %(course)s has no full price for %(day)s.")
            % {"course": group.course.name, "day": enrollment.start_date.strftime("%d.%m.%Y")}
        )
    step = ledger.step()
    rules = ledger.rules_for(ledger.assignments_on(enrollment.pk, enrollment.start_date))
    parts = build_schedule(selectors.rule_for(template), price.amount, enrollment.start_date, step)
    with transaction.atomic():
        plan = InstallmentPlan.objects.create(
            enrollment=enrollment,
            template=template,
            full_price=price.amount,
            price=price,
            created_by=actor,
            template_snapshot={
                "name": template.name,
                "parts_count": template.parts_count,
                "split_mode": template.split_mode,
                "first_due": template.first_due,
                "interval_months": template.interval_months,
                "due_day_of_month": template.due_day_of_month,
                "shares_bp": template.shares_bp(),
            },
        )
        for part, lines in part_discounts(parts, rules, step):
            ledger.create_charge(
                actor=actor,
                student_id=enrollment.student_id,
                branch_id=group.branch_id,
                kind=Charge.Kind.INSTALLMENT,
                due_date=part.due_date,
                base_amount=part.amount,
                amount=part.amount,
                suggested_amount=part.amount,
                enrollment=enrollment,
                plan=plan,
                part_no=part.part_no,
                price=price,
                discount_lines=lines,
                rebuild=False,
            )
        audit.record(
            actor,
            "billing.installment_plan.create",
            plan,
            after=_plan_state(plan),
            branch_id=group.branch_id,
        )
    return plan


def _plan_state(plan: InstallmentPlan) -> dict:
    return {
        "parts": [
            {"part": c.part_no, "due": c.due_date.isoformat(), "net": ledger.net_of(c)}
            for c in plan.charges.order_by("part_no", "id")
        ]
    }


def open_parts(plan: InstallmentPlan):
    return [c for c in plan.charges.order_by("due_date", "part_no", "id") if ledger.net_of(c) > 0]


def edit_plan(*, actor, plan: InstallmentPlan, changes: list[dict], reason: str) -> InstallmentPlan:
    """changes: [{"charge": Charge, "amount": int, "due_date": date}] for open parts.

    Amount change -> adjustment. Due-date change -> the part is cancelled by adjustment and a
    replacement part is issued. Everything is kept; a revision row records before/after.
    """
    require_perm(actor, "billing.plan.edit")
    enrollment = plan.enrollment
    ensure_branch_access(actor, enrollment.group.branch_id)
    if not reason.strip():
        raise ValidationError(_("Write the reason."))
    with transaction.atomic():
        InstallmentPlan.objects.select_for_update().get(pk=plan.pk)
        before = _plan_state(plan)
        changed = False
        for ch in changes:
            charge, amount, due = ch["charge"], ch["amount"], ch["due_date"]
            if charge.plan_id != plan.pk:
                raise ValidationError(_("Unknown part."))
            if amount < 0:
                raise ValidationError(_("The amount can't be negative."))
            current = ledger.net_of(charge)
            if due != charge.due_date:
                ledger.adjust(
                    actor=actor,
                    charge=charge,
                    delta=-current,
                    kind="plan_edit",
                    reason=reason,
                    rebuild=False,
                )
                if amount > 0:
                    ledger.create_charge(
                        actor=actor,
                        student_id=charge.student_id,
                        branch_id=charge.branch_id,
                        kind=Charge.Kind.INSTALLMENT,
                        due_date=due,
                        base_amount=amount,
                        amount=amount,
                        suggested_amount=None,
                        enrollment=enrollment,
                        plan=plan,
                        part_no=charge.part_no,
                        price=charge.price,
                        discount_lines=[],
                        description=_("Rescheduled part"),
                        rebuild=False,
                    )
                changed = True
            elif amount != current:
                ledger.adjust(
                    actor=actor,
                    charge=charge,
                    delta=amount - current,
                    kind="plan_edit",
                    reason=reason,
                    rebuild=False,
                )
                changed = True
        if not changed:
            return plan
        after = _plan_state(plan)
        InstallmentPlanRevision.objects.create(
            plan=plan, reason=reason.strip(), before=before, after=after, created_by=actor
        )
        audit.record(
            actor,
            "billing.installment_plan.edit",
            plan,
            before=before,
            after=after,
            branch_id=enrollment.group.branch_id,
            reason=reason.strip(),
            only_changes=False,
        )
        rebuild_for_student(enrollment.student_id)
    return plan
