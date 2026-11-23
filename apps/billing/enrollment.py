"""Billing's hook into the enrollment lifecycle (docs/SPEC.md 6.4.2-6.4.4, Q-4..Q-10).

Registered with students.services.register_enrollment_extension. For every enroll / move /
freeze / unfreeze / leave it shows the money consequences on the confirmation step, the admin
accepts each suggested amount or types another one (a reason is then required), and the
result is written inside the same transaction as the enrollment change.
"""

from dataclasses import dataclass, field

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.translation import gettext as _

from apps.core import dates, money
from apps.core.datemath import month_start
from apps.core.permissions import has_perm
from apps.students.models import Enrollment

from .domain import discounts as disc
from .models import Charge, DiscountAssignment, DiscountType
from .services import installments, ledger
from .services.allocation import rebuild_for_student
from .services.monthly import Line, monthly_price, side_lines

ADJ_KIND = {
    "leave": "proration_leave",
    "freeze": "proration_freeze",
    "unfreeze": "proration_join",
    "move": "move",
}


@dataclass
class Side:
    title: str
    lines: list[Line] = field(default_factory=list)
    templates: list = field(default_factory=list)  # installment enroll: [(template, price, rows)]
    chosen_template: int | None = None
    cancel_parts: list = field(default_factory=list)  # [(charge, net)]
    cancel_rows: list = field(default_factory=list)  # [(charge, net, checked)] for display
    enrollment: Enrollment | None = None
    group: object = None


def _freezes(e: Enrollment) -> list[tuple]:
    return [(f.from_date, f.to_date) for f in e.freezes.all()]


def _until(day):
    return max(dates.today(), day)


def _discount_choice(action, data):
    """(DiscountType, value) chosen on the enroll step, or (None, None)."""
    if not data or not data.get("x_discount"):
        return None, None
    dtype = DiscountType.objects.filter(pk=data.get("x_discount"), is_active=True).first()
    if dtype is None:
        return None, None
    value = dtype.value
    raw = (data.get("x_discount_value") or "").strip()
    if raw and dtype.allow_custom_value:
        from .forms import parse_percent_bp

        try:
            value = parse_percent_bp(raw) if dtype.kind == "percent" else money.parse_amount(raw)
        except ValueError:
            value = dtype.value
    return dtype, value


def _monthly_side(
    prefix,
    title,
    *,
    group,
    enrollment,
    start,
    end,
    freezes,
    from_day,
    new_until,
    first_day,
    extra_rules=(),
):
    lines = side_lines(
        prefix=prefix,
        group=group,
        enrollment=enrollment,
        start=start,
        end=end,
        freezes=freezes,
        from_month=month_start(from_day),
        new_until=new_until,
        first_day=first_day,
        extra_rules=list(extra_rules),
    )
    return Side(title=title, lines=lines, enrollment=enrollment, group=group)


def _cancel_side(title, e: Enrollment, after_day):
    plan = getattr(e, "installment_plan", None)
    if plan is None:
        return None
    parts = [(c, ledger.net_of(c)) for c in installments.open_parts(plan) if c.due_date > after_day]
    return Side(title=title, cancel_parts=parts, enrollment=e, group=e.group) if parts else None


def _install_side(title, group, start, data, extra_rules, enrollment=None):
    side = Side(title=title, group=group, enrollment=enrollment)
    templates = installments.templates_for(group)
    chosen = None
    if data and data.get("x_template"):
        chosen = next((t for t in templates if str(t.pk) == data.get("x_template")), None)
    chosen = chosen or (templates[0] if templates else None)
    side.chosen_template = chosen.pk if chosen else None
    for t in templates:
        price, rows = installments.preview(group, t, start, extra_rules)
        side.templates.append((t, price, rows))
    if not templates:
        side.lines.append(
            Line(
                key="ierr",
                kind="error",
                message=_("No active installment template fits this course. Add one in Settings."),
            )
        )
    elif side.templates[0][1] is None:
        side.lines.append(
            Line(
                key="ierr",
                kind="error",
                message=_("The course %(course)s has no full price for %(day)s.")
                % {"course": group.course.name, "day": dates.format_date(start)},
            )
        )
    return side


def compute(action, data=None, *, result=None) -> list[Side]:
    """Sides with lines. Before the action (`result` None) the new state is simulated from
    the action; after it (`result` given) the real database state is used."""
    k, day = action.kind, action.effective_date
    after = result is not None
    sides: list[Side] = []
    if k == "enroll":
        group = action.group
        dtype, value = _discount_choice(action, data)
        extra = (
            [] if after or dtype is None else [disc.Rule(key=dtype, kind=dtype.kind, value=value)]
        )
        new_e = result.enrollment if after else None
        if group.course.is_monthly:
            sides.append(
                _monthly_side(
                    "n",
                    group.name,
                    group=group,
                    enrollment=new_e,
                    start=day,
                    end=None,
                    freezes=[],
                    from_day=day,
                    new_until=_until(day),
                    first_day=day,
                    extra_rules=extra,
                )
            )
        else:
            if after:
                extra = ledger.rules_for(ledger.assignments_on(new_e.pk, day))
            sides.append(_install_side(group.name, group, day, data, extra, new_e))
        return sides

    e = Enrollment.objects.select_related("group", "group__course").get(pk=action.enrollment.pk)
    group = e.group
    if k in ("leave", "freeze", "unfreeze"):
        if not group.course.is_monthly:
            if k == "leave":
                side = _cancel_side(group.name, e, day)
                if side:
                    sides.append(side)
            return sides  # freezing doesn't change an installment plan
        freezes = _freezes(e)
        end = e.end_date
        if not after:
            if k == "leave":
                end = day
            elif k == "freeze":
                freezes.append((day, None))
            else:
                freezes = [(f, day if t is None else t) for f, t in freezes]
        until = _until(day) if k == "unfreeze" else None
        sides.append(
            _monthly_side(
                "o",
                group.name,
                group=group,
                enrollment=e,
                start=e.start_date,
                end=end,
                freezes=freezes,
                from_day=day,
                new_until=until,
                first_day=day if k == "unfreeze" else None,
            )
        )
        return sides

    # move
    target = action.group
    new_e = result.enrollment if after else None
    same_course = target.course_id == group.course_id
    if group.course.is_monthly:
        old = _monthly_side(
            "o",
            group.name,
            group=group,
            enrollment=e,
            start=e.start_date,
            end=day,
            freezes=_freezes(e),
            from_day=day,
            new_until=None,
            first_day=None,
        )
    else:
        old = None if same_course else _cancel_side(group.name, e, day)
    if target.course.is_monthly:
        new = _monthly_side(
            "n",
            target.name,
            group=target,
            enrollment=new_e,
            start=day,
            end=None,
            freezes=[],
            from_day=day,
            new_until=_until(day),
            first_day=day,
        )
    else:
        new = None if same_course else _install_side(target.name, target, day, data, [], new_e)
    if same_course and group.course.is_monthly:
        # Same course and same price: the month already charged stays as it is (SPEC Q-6).
        move_month = month_start(day)
        old_charge = Charge.objects.filter(
            enrollment=e, kind="monthly", period_month=move_month
        ).first()
        price = monthly_price(target, day)
        if old_charge and price and old_charge.base_amount == price.amount:
            old.lines = [ln for ln in old.lines if ln.month != move_month]
            new.lines = [ln for ln in new.lines if ln.month != move_month]
    return [s for s in (old, new) if s and (s.lines or s.cancel_parts or s.templates)]


def _value(line: Line, data) -> int:
    if not data or f"x_{line.key}" not in data:
        return line.suggested
    try:
        return money.parse_amount(data.get(f"x_{line.key}"))
    except ValueError as exc:
        raise ValidationError(_("Enter a whole amount in so'm, for example 450 000.")) from exc


def _cancel_checked(charge, data) -> bool:
    if not data or not data.get("x_seen"):
        return True  # default: cancel future parts
    return data.get(f"x_cp{charge.pk}") == "1"


def errors_for(sides, data) -> list[str]:
    errors = []
    reason = (data.get("x_reason") or "").strip() if data else ""
    differs = False
    for side in sides:
        for line in side.lines:
            if line.kind == "error":
                errors.append(line.message)
                continue
            try:
                value = _value(line, data)
            except ValidationError as exc:
                errors.extend(exc.messages)
                continue
            if value < 0:
                errors.append(_("The amount can't be negative."))
            differs |= value != line.suggested
        for charge, _net in side.cancel_parts:
            differs |= not _cancel_checked(charge, data)
    if differs and not reason:
        errors.append(_("You changed a suggested amount: write the reason."))
    return errors


class BillingExtension:
    key = "billing"
    template = "billing/_enrollment_confirm.html"

    def preview(self, action, data=None):
        sides = compute(action, data)
        if not sides:
            return None
        for side in sides:
            for line in side.lines:
                line.posted = (data or {}).get(f"x_{line.key}", "")
            side.cancel_rows = [(c, net, _cancel_checked(c, data)) for c, net in side.cancel_parts]
        discount_types = []
        if action.kind == "enroll":
            model = "monthly" if action.group.course.is_monthly else "installment"
            discount_types = DiscountType.objects.filter(
                is_active=True, applies_to__in=[model, "any"]
            )
        return {
            "sides": sides,
            "data": data or {},
            "discount_types": discount_types,
            "errors": errors_for(sides, data) if data and data.get("tasdiq") else [],
        }

    def validate(self, action, data):
        return errors_for(compute(action, data), data)

    def apply(self, action, data, *, actor, result):
        reason = (data.get("x_reason") or "").strip() if data else ""
        student = action.student
        if action.kind == "enroll":
            dtype, value = _discount_choice(action, data)
            if dtype is not None:
                if value != dtype.value and not has_perm(actor, "billing.discount.custom"):
                    raise PermissionDenied
                DiscountAssignment.objects.create(
                    enrollment=result.enrollment,
                    discount_type=dtype,
                    value=value,
                    valid_from=action.effective_date,
                    reason=reason,
                    created_by=actor,
                )
        sides = compute(action, data, result=result)
        errors = (
            errors_for(sides, data)
            if data
            else [ln.message for s in sides for ln in s.lines if ln.kind == "error"]
        )
        if errors:
            raise ValidationError(errors)
        adj_kind = ADJ_KIND.get(action.kind, "correction")
        for side in sides:
            enrollment = side.enrollment or result.enrollment
            for line in side.lines:
                from .services.monthly import apply_line

                apply_line(
                    line,
                    actor=actor,
                    value=_value(line, data),
                    reason=reason,
                    student=student,
                    enrollment=enrollment,
                    adj_kind=adj_kind,
                )
            for charge, net in side.cancel_parts:
                if _cancel_checked(charge, data):
                    ledger.adjust(
                        actor=actor,
                        charge=charge,
                        delta=-net,
                        kind="cancellation",
                        reason=reason or _("Left the course"),
                        rebuild=False,
                    )
            if side.templates and side.chosen_template:
                template = next(t for t, _p, _r in side.templates if t.pk == side.chosen_template)
                installments.create_plan(actor=actor, enrollment=enrollment, template=template)
        rebuild_for_student(student.pk)
