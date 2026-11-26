"""The parent's menu in the bot (docs/SPEC.md §21): balance and the next payment, attendance
for the last 30 days, the last payments and the lesson schedule.

A parent is matched by the phone they shared (Chat.phone): they see only the students with
that phone number. A parent with several children gets every child in one answer."""

import datetime as dt

from django.utils.translation import gettext as _

from apps.billing import selectors as billing_selectors
from apps.core import dates
from apps.core.money import format_som
from apps.students import selectors as student_selectors
from apps.students.models import Attendance, Enrollment, Lesson, ScheduleSlot

from ..models import Chat

BALANCE, ATTENDANCE, PAYMENTS, SCHEDULE = "balance", "attendance", "payments", "schedule"
ICONS = {BALANCE: "💰", ATTENDANCE: "📅", PAYMENTS: "🧾", SCHEDULE: "🗓"}
MAX_ABSENT_DATES = 10


def _labels() -> dict[str, str]:
    return {
        BALANCE: _("Balance"),
        ATTENDANCE: _("Attendance"),
        PAYMENTS: _("Payments"),
        SCHEDULE: _("Lesson schedule"),
    }


def button_text(key: str) -> str:
    return f"{ICONS[key]} {_labels()[key]}"


def keyboard() -> dict:
    """A reply keyboard that stays under the message box."""
    return {
        "keyboard": [
            [{"text": button_text(BALANCE)}, {"text": button_text(ATTENDANCE)}],
            [{"text": button_text(PAYMENTS)}, {"text": button_text(SCHEDULE)}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def which(text: str) -> str | None:
    """The menu item a message means: the button text, or the label typed by hand."""
    t = (text or "").strip().lower()
    for key, label in _labels().items():
        if t in (button_text(key).lower(), label.lower()):
            return key
    return None


def children(chat: Chat) -> list:
    if chat.kind != Chat.Kind.PARENT or not chat.phone:
        return []
    return list(student_selectors.find_by_phones([chat.phone]).order_by("last_name", "first_name"))


def _balance(student) -> list[str]:
    v = billing_selectors.parent_view(student.pk)
    lines = []
    if v["balance"] < 0:
        lines.append(_("Debt: %(a)s") % {"a": format_som(-v["balance"])})
    elif v["balance"] > 0:
        lines.append(_("Paid in advance: %(a)s") % {"a": format_som(v["balance"])})
    else:
        lines.append(_("Everything is paid."))
    if v["overdue"]:
        lines.append(_("Overdue: %(a)s") % {"a": format_som(v["overdue"])})
    if v["next_due"]:
        lines.append(
            _("Next payment: %(a)s by %(d)s")
            % {"a": format_som(v["next_amount"]), "d": dates.format_date(v["next_due"])}
        )
    return lines


def _attendance(student, today: dt.date) -> list[str]:
    since = today - dt.timedelta(days=30)
    marks = list(
        Attendance.objects.filter(student=student, lesson__date__gte=since, lesson__date__lte=today)
        .select_related("lesson")
        .order_by("lesson__date", "lesson__start_time")
    )
    if not marks:
        return [_("No marked lessons in the last 30 days.")]
    came = sum(1 for m in marks if m.status == Attendance.Status.PRESENT)
    missed = [m.lesson.date for m in marks if m.status == Attendance.Status.ABSENT]
    lines = [_("Last 30 days: came %(c)s of %(n)s lessons.") % {"c": came, "n": len(marks)}]
    if missed:
        shown = ", ".join(dates.format_date(d) for d in missed[-MAX_ABSENT_DATES:])
        lines.append(_("Missed: %(dates)s") % {"dates": shown})
    return lines


def _payments(student) -> list[str]:
    rows = billing_selectors.parent_view(student.pk)["payments"]
    if not rows:
        return [_("No payments yet.")]
    out = []
    for p, cancelled in rows:
        line = f"{dates.format_date(p.paid_on)} — {format_som(p.amount)} ({p.receipt_number})"
        if cancelled:
            line += " — " + _("cancelled")
        out.append(line)
    return out


def _schedule(student, today: dt.date) -> list[str]:
    enrollments = Enrollment.objects.filter(
        student=student, status__in=Enrollment.OPEN
    ).select_related("group", "group__teacher")
    if not enrollments:
        return [_("Not in a group now.")]
    out = []
    for e in enrollments:
        g = e.group
        slots = ScheduleSlot.objects.filter(group=g).select_related("room")
        days = ", ".join(
            f"{s.get_weekday_display()} {s.start_time:%H:%M}–{s.end_time:%H:%M}" for s in slots
        )
        head = g.name + (f" ({g.teacher.full_name})" if g.teacher else "")
        out.append(f"{head}: {days or '—'}")
        nxt = (
            Lesson.objects.filter(group=g, date__gte=today)
            .exclude(status=Lesson.Status.CANCELLED)
            .order_by("date", "start_time")
            .first()
        )
        if nxt:
            out.append(
                _("Next lesson: %(d)s at %(t)s")
                % {"d": dates.format_date(nxt.date), "t": f"{nxt.start_time:%H:%M}"}
            )
    return out


def answer(chat: Chat, key: str) -> str:
    """The text for one menu button, for every child of this parent."""
    kids = children(chat)
    if not kids:
        return _(
            "We couldn't find a student with your phone number any more. Please ask the "
            "center's administrator."
        )
    today = dates.today()
    parts = [f"{ICONS[key]} {_labels()[key]}"]
    for s in kids:
        if key == BALANCE:
            lines = _balance(s)
        elif key == ATTENDANCE:
            lines = _attendance(s, today)
        elif key == PAYMENTS:
            lines = _payments(s)
        else:
            lines = _schedule(s, today)
        parts.append("\n".join([f"👤 {s.full_name}", *lines]))
    return "\n\n".join(parts)
