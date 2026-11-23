"""Billing import kinds: opening balances and discounts (docs/SPEC.md 6.4.11, 6.5)."""

from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core import dates
from apps.core import phone as phones
from apps.core.text import search_key
from apps.students import services as student_services
from apps.students.models import Enrollment, Student
from apps.students.services.importing import (
    ImportKind,
    ParseResult,
    RowError,
    as_date,
    as_phone,
    text,
)

from .forms import parse_percent_bp
from .models import Charge, DiscountType, Payment, PaymentMethod
from .services import discounts, ledger
from .services.allocation import rebuild_for_student
from .services.payments import next_receipt

O_PHONE = gettext_lazy("Student's or parent's phone")
O_AMOUNT = gettext_lazy("Amount (debt +, credit -)")
O_DATE = gettext_lazy("Debt date")
O_NOTE = gettext_lazy("Comment")

OPENING_COLUMNS = [
    (O_PHONE, "+998901234567"),
    (O_AMOUNT, 450000),
    (O_DATE, "10.10.2026"),
    (O_NOTE, ""),
]


def _find_student(phone, branch):
    return Student.objects.filter(branch=branch).filter(
        Q(phone=phone) | Q(parent_phone=phone) | Q(extra_phone=phone)
    )


def parse_opening(raw, ctx) -> ParseResult:
    result = ParseResult()
    seen = {}
    for number, row in raw:
        errs = []
        try:
            ph = as_phone(row.get(str(O_PHONE)))
        except phones.InvalidPhone:
            ph = ""
            errs.append(RowError(number, _("a phone number is wrong (use +998 90 123 45 67)")))
        student = None
        if ph:
            matches = list(_find_student(ph, ctx.branch)[:2])
            if not matches:
                errs.append(RowError(number, _("no student with this phone in this branch")))
            elif len(matches) > 1:
                errs.append(
                    RowError(
                        number, _("several students have this phone; use the student's own phone")
                    )
                )
            else:
                student = matches[0]
        elif not errs:
            errs.append(RowError(number, _("the phone is empty")))
        try:
            amount = int(text(row.get(str(O_AMOUNT))).replace(" ", "").replace(" ", ""))
            if amount == 0:
                raise ValueError
        except ValueError:
            amount = None
            errs.append(RowError(number, _("the amount must be a whole number, not 0")))
        try:
            day = as_date(row.get(str(O_DATE)))
        except ValueError:
            day = None
            errs.append(RowError(number, _("a date is wrong (use DD.MM.YYYY)")))
        if student is not None:
            if student.pk in seen:
                errs.append(
                    RowError(
                        number,
                        _("the student repeats row %(n)d of the file") % {"n": seen[student.pk]},
                    )
                )
            seen[student.pk] = number
            has_opening = Charge.objects.filter(
                student=student, kind=Charge.Kind.OPENING_BALANCE
            ).exists() or (
                Payment.objects.filter(student=student, provider_code="opening_balance").exists()
            )
            if has_opening:
                errs.append(RowError(number, _("this student already has an opening balance")))
        if errs:
            result.errors.extend(errs)
            continue
        result.rows.append(
            {"student": student, "amount": amount, "date": day, "note": text(row.get(str(O_NOTE)))}
        )
    return result


def commit_opening(rows, ctx) -> dict:
    method = PaymentMethod.objects.get(provider_code="opening_balance")
    today = dates.today()
    for r in rows:
        student = r["student"]
        if r["amount"] > 0:
            ledger.create_charge(
                actor=ctx.actor,
                student_id=student.pk,
                branch_id=student.branch_id,
                kind=Charge.Kind.OPENING_BALANCE,
                due_date=r["date"] or today,
                base_amount=r["amount"],
                amount=r["amount"],
                suggested_amount=None,
                description=r["note"] or _("Opening balance"),
                import_batch=ctx.batch,
                discount_lines=[],
                rebuild=False,
            )
        else:
            seq, number = next_receipt(student.branch)
            Payment.objects.create(
                student=student,
                branch=student.branch,
                kind=Payment.Kind.PAYMENT,
                amount=-r["amount"],
                method=method,
                provider_code=method.provider_code,
                paid_on=today,
                received_by=ctx.actor,
                comment=r["note"] or _("Opening balance"),
                receipt_seq=seq,
                receipt_number=number,
                import_batch=ctx.batch,
            )
        rebuild_for_student(student.pk)
    return {"balances_created": len(rows)}


D_PHONE = gettext_lazy("Student's or parent's phone")
D_GROUP = gettext_lazy("Group name")
D_TYPE = gettext_lazy("Discount type")
D_VALUE = gettext_lazy("Custom value")
D_FROM = gettext_lazy("From")

DISCOUNT_COLUMNS = [
    (D_PHONE, "+998901234567"),
    (D_GROUP, "Matematika 7-A"),
    (D_TYPE, "Aka-uka / opa-singil"),
    (D_VALUE, ""),
    (D_FROM, "01.12.2026"),
]


def parse_discounts(raw, ctx) -> ParseResult:
    result = ParseResult()
    types = {search_key(t.name): t for t in DiscountType.objects.filter(is_active=True)}
    for number, row in raw:
        errs = []
        try:
            ph = as_phone(row.get(str(D_PHONE)))
        except phones.InvalidPhone:
            ph = ""
        students = list(_find_student(ph, ctx.branch)[:2]) if ph else []
        if len(students) != 1:
            errs.append(RowError(number, _("no student with this phone in this branch")))
        dtype = types.get(search_key(text(row.get(str(D_TYPE)))))
        if dtype is None:
            errs.append(
                RowError(
                    number,
                    _('discount type "%(v)s" not found in Settings')
                    % {"v": text(row.get(str(D_TYPE)))},
                )
            )
        enrollment = None
        if len(students) == 1:
            enrollment = (
                Enrollment.objects.filter(
                    student=students[0],
                    group__name__iexact=text(row.get(str(D_GROUP))),
                    status__in=Enrollment.OPEN,
                )
                .select_related("group", "group__course")
                .first()
            )
            if enrollment is None:
                errs.append(
                    RowError(
                        number,
                        _('the student is not in group "%(v)s"')
                        % {"v": text(row.get(str(D_GROUP)))},
                    )
                )
        value = None
        raw_value = text(row.get(str(D_VALUE)))
        if raw_value and dtype is not None:
            try:
                value = (
                    parse_percent_bp(raw_value)
                    if dtype.kind == "percent"
                    else int(raw_value.replace(" ", ""))
                )
            except ValueError:
                errs.append(RowError(number, _("the custom value is wrong")))
        try:
            start = as_date(row.get(str(D_FROM))) or dates.today()
        except ValueError:
            start = None
            errs.append(RowError(number, _("a date is wrong (use DD.MM.YYYY)")))
        if errs:
            result.errors.extend(errs)
            continue
        result.rows.append({"enrollment": enrollment, "type": dtype, "value": value, "from": start})
    return result


def commit_discounts(rows, ctx) -> dict:
    for r in rows:
        discounts.assign(
            actor=ctx.actor,
            enrollment=r["enrollment"],
            discount_type=r["type"],
            valid_from=r["from"],
            value=r["value"],
            reason=_("Imported from Excel"),
        )
    return {"discounts_created": len(rows)}


def register():
    student_services.register_import_kind(
        ImportKind(
            key="opening_balances",
            label=gettext_lazy("Opening balances"),
            columns=OPENING_COLUMNS,
            parse=parse_opening,
            commit=commit_opening,
            help_text=gettext_lazy(
                "Import students first. Debt is a positive amount, credit negative."
            ),
        )
    )
    student_services.register_import_kind(
        ImportKind(
            key="discounts",
            label=gettext_lazy("Discounts"),
            columns=DISCOUNT_COLUMNS,
            parse=parse_discounts,
            commit=commit_discounts,
            help_text=gettext_lazy(
                "Import students into groups first. Applies to charges from the start date."
            ),
        )
    )
