"""Salary reads (docs/SPEC.md §13). The Direktor sees everything; a teacher only their own."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.http import Http404

from apps.billing import services as billing_services
from apps.billing.models import Allocation
from apps.core import dates
from apps.core.datemath import add_months, month_start
from apps.core.permissions import has_perm, require_perm
from apps.core.roles import Role
from apps.core.system_settings import get_setting
from apps.students.models import Group, Student

from .domain import calc
from .formatting import format_percent
from .models import Adjustment, Advance, FixedLine, Line, Month, Payout, Rate, StaffPay

CLOSED, OPEN, LATER = "closed", "open", "later"


# --- months ---------------------------------------------------------------------------------


def start_month() -> dt.date:
    value = get_setting("salaries.start_month")
    return dt.date(value // 100, value % 100, 1)


def closed_months() -> set[dt.date]:
    return set(Month.objects.values_list("month", flat=True))


def open_month() -> dt.date:
    """The first month from the start month that is not closed yet."""
    closed = closed_months()
    m = start_month()
    while m in closed:
        m = add_months(m, 1)
    return m


def month_state(month: dt.date) -> str:
    if Month.objects.filter(month=month).exists():
        return CLOSED
    return OPEN if month == open_month() else LATER


def months_for_picker() -> list[dt.date]:
    """Start month up to the later of the open month and the current month, newest first."""
    last = max(open_month(), month_start(dates.today()))
    out, m = [], start_month()
    while m <= last:
        out.append(m)
        m = add_months(m, 1)
    return list(reversed(out))


def parse_month(raw: str | None) -> dt.date | None:
    """ "12.2026" -> 2026-12-01."""
    if not raw:
        return None
    try:
        mm, yyyy = raw.strip().split(".")
        return dt.date(int(yyyy), int(mm), 1)
    except (ValueError, TypeError):
        return None


# --- rates ----------------------------------------------------------------------------------


def rate_rows() -> dict[int, list[calc.RateRow]]:
    rows = defaultdict(list)
    for r in Rate.objects.values("teacher_id", "effective_from", "created_at", "id", "rate_bp"):
        rows[r["teacher_id"]].append(
            calc.RateRow(r["effective_from"], (r["created_at"], r["id"]), r["rate_bp"])
        )
    return rows


def rate_lookup():
    rows, default = rate_rows(), get_setting("salaries.default_rate_bp")

    def rate_for(teacher_id: int, month: dt.date) -> int:
        return calc.rate_on(rows.get(teacher_id, []), month, default)

    return rate_for


def teachers():
    return get_user_model().objects.filter(role=Role.TEACHER).order_by("full_name")


SALARIED_ROLES = (Role.TEACHER, Role.BRANCH_ADMIN, Role.SALES_MANAGER)


def salaried():
    """Everyone who can have a salary sheet: teachers (share) and staff (fixed pay)."""
    return get_user_model().objects.filter(role__in=SALARIED_ROLES).order_by("full_name")


def staff():
    """Administrators and sales managers: the people with a fixed monthly salary."""
    return (
        get_user_model()
        .objects.filter(role__in=(Role.BRANCH_ADMIN, Role.SALES_MANAGER))
        .order_by("full_name")
    )


def fixed_amounts(month: dt.date) -> dict[int, int]:
    """{user_id: fixed salary in force in `month`} for active people with one (> 0)."""
    rows = defaultdict(list)
    for r in StaffPay.objects.filter(user__is_active=True).values(
        "user_id", "effective_from", "created_at", "id", "amount"
    ):
        rows[r["user_id"]].append(
            calc.PayRow(r["effective_from"], (r["created_at"], r["id"]), r["amount"])
        )
    out = {uid: calc.fixed_on(rs, month) for uid, rs in rows.items()}
    return {uid: a for uid, a in out.items() if a > 0}


def _in_branch(people, branch_id: int | None):
    """People linked to the branch picked in the top bar (None = everyone)."""
    if not branch_id:
        return people
    return people.filter(branch_links__branch_id=branch_id).distinct()


def current_staff_pay(branch_id: int | None = None) -> list[dict]:
    """Sozlamalar -> Xodimlar maoshi: each administrator / manager, today's fixed salary and
    history."""
    month = month_start(dates.today())
    history = defaultdict(list)
    for r in StaffPay.objects.select_related("created_by").order_by(
        "-effective_from", "-created_at"
    ):
        history[r.user_id].append(r)
    now = fixed_amounts(month)
    people = staff().filter(is_active=True) | get_user_model().objects.filter(pk__in=history)
    return [
        {"user": u, "amount": now.get(u.pk, 0), "history": history.get(u.pk, [])}
        for u in _in_branch(people.distinct(), branch_id).order_by("full_name")
    ]


def current_rates(branch_id: int | None = None) -> list[dict]:
    rate_for = rate_lookup()
    month = month_start(dates.today())
    history = defaultdict(list)
    for r in Rate.objects.select_related("created_by").order_by("-effective_from", "-created_at"):
        r.rate_text = format_percent(r.rate_bp)
        history[r.teacher_id].append(r)
    return [
        {
            "teacher": t,
            "rate_bp": rate_for(t.pk, month),
            "rate": format_percent(rate_for(t.pk, month)),
            "own": bool(history.get(t.pk)),
            "history": history.get(t.pk, []),
        }
        for t in _in_branch(teachers(), branch_id).order_by("full_name")
        if t.is_active or history.get(t.pk)
    ]


# --- the calculation ------------------------------------------------------------------------


def live_basis(up_to: dt.date) -> dict[calc.Key, int]:
    """Money FIFO-applied to group charges, by (student, group, payment month)."""
    rows = (
        Allocation.objects.filter(
            charge__group__isnull=False,
            payment__paid_on__gte=start_month(),
            payment__paid_on__lt=add_months(up_to, 1),
        )
        .annotate(pm=TruncMonth("payment__paid_on"))
        .values("charge__student_id", "charge__group_id", "pm")
        .annotate(t=Sum("amount"))
    )
    return {(r["charge__student_id"], r["charge__group_id"], r["pm"]): int(r["t"]) for r in rows}


def accounted() -> dict[calc.Key, int]:
    rows = Line.objects.values("student_id", "group_id", "payment_month").annotate(t=Sum("base"))
    return {(r["student_id"], r["group_id"], r["payment_month"]): int(r["t"]) for r in rows}


def draft(month: dt.date) -> list[calc.DraftLine]:
    """Lines the open month would freeze if it were closed now."""
    return calc.draft_lines(
        month,
        live_basis(month),
        accounted(),
        dict(Group.objects.values_list("id", "teacher_id")),
        rate_lookup(),
        billing_services.percent_of,
    )


# --- sheets ---------------------------------------------------------------------------------


@dataclass
class Sheet:
    teacher: object
    month: dt.date
    state: str
    lines: list = field(default_factory=list)  # dicts: student, group, payment_month, ...
    adjustments: list = field(default_factory=list)
    totals: calc.Totals = field(default_factory=calc.Totals)
    payout: Payout | None = None
    rate: str = ""
    advances: list = field(default_factory=list)  # Advance rows still in force

    @property
    def payable(self) -> bool:
        return self.state == CLOSED and self.payout is None and self.totals.to_pay > 0


def _line_dicts(lines) -> list[dict]:
    students = Student.objects.in_bulk({line.student_id for line in lines})
    groups = Group.objects.in_bulk({line.group_id for line in lines})
    out = [
        {
            "student": students.get(line.student_id),
            "group": groups.get(line.group_id),
            "payment_month": line.payment_month,
            "kind": line.kind,
            "base": line.base,
            "rate_bp": line.rate_bp,
            "rate": format_percent(line.rate_bp),
            "amount": line.amount,
        }
        for line in lines
    ]
    out.sort(key=lambda d: (d["kind"] != "share", str(d["group"]), str(d["student"])))
    return out


def active_advances(month: dt.date, ids=None) -> dict[int, list]:
    """{person: [advances given for `month` and not cancelled]}."""
    qs = Advance.objects.filter(
        month=month, kind=Advance.Kind.ADVANCE, cancelled_by__isnull=True
    ).select_related("branch", "method", "created_by")
    if ids is not None:
        qs = qs.filter(person_id__in=ids)
    out = defaultdict(list)
    for a in qs:
        out[a.person_id].append(a)
    return out


def _active_payouts(month: dt.date) -> dict[int, Payout]:
    payouts = Payout.objects.filter(
        month__month=month, kind=Payout.Kind.PAYOUT, cancelled_by__isnull=True
    ).select_related("created_by")
    return {p.teacher_id: p for p in payouts}


def sheets_for(month: dt.date, teacher_ids: set[int] | None = None) -> list[Sheet]:
    state = month_state(month)
    if state == CLOSED:
        lines = list(Line.objects.filter(month__month=month))
        fixed = dict(FixedLine.objects.filter(month__month=month).values_list("user_id", "amount"))
    elif state == OPEN:
        lines = draft(month)
        fixed = fixed_amounts(month)
    else:
        lines, fixed = [], {}
    adjustments = list(Adjustment.objects.filter(month=month).select_related("created_by"))
    payouts = _active_payouts(month) if state == CLOSED else {}
    advances = active_advances(month)
    by_teacher = defaultdict(list)
    for line in lines:
        by_teacher[line.teacher_id].append(line)
    adj_by_teacher = defaultdict(list)
    for a in adjustments:
        adj_by_teacher[a.teacher_id].append(a)
    ids = set(by_teacher) | set(adj_by_teacher) | set(fixed) | set(advances)
    if teacher_ids is not None:
        ids = (ids | teacher_ids) & teacher_ids
    else:
        ids |= set(teachers().filter(is_active=True).values_list("pk", flat=True))
    people = get_user_model().objects.in_bulk(ids)
    sheets = []
    for tid in ids:
        mine, adj = by_teacher.get(tid, []), adj_by_teacher.get(tid, [])
        totals = calc.totals(mine, [(a.kind, a.amount) for a in adj], fixed.get(tid, 0))
        given = advances.get(tid, [])
        totals.advances = sum(a.amount for a in given)
        sheets.append(
            Sheet(
                teacher=people[tid],
                month=month,
                state=state,
                lines=mine,
                adjustments=adj,
                totals=totals,
                payout=payouts.get(tid),
                advances=given,
            )
        )
    sheets.sort(key=lambda s: s.teacher.full_name)
    return sheets


def month_overview(user, month: dt.date) -> dict:
    require_perm(user, "salaries.manage")
    sheets = sheets_for(month)
    grand = calc.Totals()
    for s in sheets:
        for f in ("paid", "share", "corrections", "fixed", "bonuses", "deductions", "advances"):
            setattr(grand, f, getattr(grand, f) + getattr(s.totals, f))
    return {
        "month": month,
        "state": month_state(month),
        "open_month": open_month(),
        "sheets": sheets,
        "grand": grand,
        "paid_out": sum(s.payout.amount for s in sheets if s.payout),
        "can_close": month_state(month) == OPEN and month <= month_start(dates.today()),
    }


def sheet(user, teacher_id: int, month: dt.date) -> Sheet:
    """One teacher's sheet. The Direktor may open any; a teacher only their own (404)."""
    if not has_perm(user, "salaries.manage"):
        if not has_perm(user, "salaries.view_own"):
            raise PermissionDenied
        if teacher_id != user.pk:
            raise Http404
    person = salaried().filter(pk=teacher_id).first()
    if person is None:
        raise Http404
    result = sheets_for(month, {teacher_id})[0]
    result.lines = _line_dicts(result.lines)
    if person.role == Role.TEACHER:
        result.rate = format_percent(rate_lookup()(teacher_id, month))
    return result


def own_months(user) -> list[dict]:
    """A teacher's months, newest first: total and whether it was paid out."""
    require_perm(user, "salaries.view_own")
    out = []
    for m in months_for_picker():
        s = sheets_for(m, {user.pk})[0]
        out.append({"month": m, "state": s.state, "total": s.totals.total, "payout": s.payout})
    return out


def own_summary(user) -> dict:
    """Dashboard widget for a teacher: the open month so far."""
    m = open_month()
    s = sheets_for(m, {user.pk})[0]
    return {"month": m, "totals": s.totals, "state": s.state}


# --- the Kassa (billing's cash-source hook, SPEC §24) ----------------------------------------


def cash_lines(branch_id: int, day: dt.date) -> list:
    """Salary money out of a branch's Kassa on a day: advances and month-end payouts, and
    their cancellations coming back in."""
    from django.urls import reverse
    from django.utils.translation import gettext as _

    from apps.billing.services.cash import CashLine

    out = []
    for a in Advance.objects.filter(branch_id=branch_id, given_on=day).select_related(
        "person", "created_by"
    ):
        cancel = a.kind == Advance.Kind.CANCEL
        out.append(
            CashLine(
                source="salaries",
                method_id=a.method_id,
                direction="in" if cancel else "out",
                amount=a.amount,
                at=a.created_at,
                by_name=a.created_by.full_name,
                description=_("Salary advance: %(name)s") % {"name": a.person.full_name},
                kind_label=_("Cancelled") if cancel else "",
                url=reverse("salaries:sheet", args=[a.person_id]) + f"?oy={a.month:%m.%Y}",
            )
        )
    for p in Payout.objects.filter(branch_id=branch_id, paid_on=day).select_related(
        "teacher", "created_by", "month"
    ):
        cancel = p.kind == Payout.Kind.CANCEL
        out.append(
            CashLine(
                source="salaries",
                method_id=p.method_id,
                direction="in" if cancel else "out",
                amount=p.amount,
                at=p.created_at,
                by_name=p.created_by.full_name,
                description=_("Salary: %(name)s, %(month)s")
                % {"name": p.teacher.full_name, "month": f"{p.month.month:%m.%Y}"},
                kind_label=_("Cancelled") if cancel else "",
                url=reverse("salaries:sheet", args=[p.teacher_id]) + f"?oy={p.month.month:%m.%Y}",
            )
        )
    return out


def cash_active_days(since: dt.date, until: dt.date) -> set:
    days = set(
        Advance.objects.filter(given_on__gte=since, given_on__lte=until).values_list(
            "branch_id", "given_on"
        )
    )
    days |= set(
        Payout.objects.filter(
            branch__isnull=False, paid_on__gte=since, paid_on__lte=until
        ).values_list("branch_id", "paid_on")
    )
    return days
