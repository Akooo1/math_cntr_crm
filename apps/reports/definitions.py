"""The module 1 reports (brief: revenue and collections by branch, month, course and payment
method; total and overdue debt; lead conversion by source and by manager)."""

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.core.reports import Col, ReportDef, Result, register_report
from apps.crm.models import LeadSource

from . import queries

FIN = _("Finance")
LEADS = _("Leads")


def _total(rows, keys):
    return [sum(r[k] for r in rows) for k in keys]


def monthly(user, p) -> Result:
    rows = queries.by_month(user, p.branch_id, p.date_from, p.date_to)
    data = [[r["month"], r["charged"], r["collected"], r["collected"] - r["charged"]] for r in rows]
    charged, collected = _total(rows, ["charged", "collected"])
    return Result(
        columns=[
            Col(_("Month"), "month"),
            Col(_("Charged"), "money"),
            Col(_("Collected"), "money"),
            Col(_("Difference"), "money"),
        ],
        rows=data,
        totals=[_("Total"), charged, collected, collected - charged],
        note=_(
            "Charged = charges due in the month, after discounts and corrections. "
            "Collected = payments minus reversals and refunds."
        ),
    )


def branches(user, p) -> Result:
    rows = queries.by_branch(user, p.branch_id, p.date_from, p.date_to)
    keys = ["charged", "collected", "open", "overdue"]
    return Result(
        columns=[
            Col(_("Branch")),
            Col(_("Charged"), "money"),
            Col(_("Collected"), "money"),
            Col(_("Unpaid now"), "money"),
            Col(_("Overdue now"), "money"),
        ],
        rows=[[r["branch"].name, *[r[k] for k in keys]] for r in rows],
        totals=[_("Total"), *_total(rows, keys)],
    )


def courses(user, p) -> Result:
    rows = queries.by_course(user, p.branch_id, p.date_from, p.date_to)
    return Result(
        columns=[Col(_("Course")), Col(_("Charged"), "money"), Col(_("Collected"), "money")],
        rows=[
            [r["course"] or _("Not tied to a course"), r["charged"], r["collected"]] for r in rows
        ],
        totals=[_("Total"), *_total(rows, ["charged", "collected"])],
        note=_(
            "Collected by course counts the money from the period's payments that went to "
            "that course's charges. Credit not yet used is not tied to a course."
        ),
    )


def methods(user, p) -> Result:
    rows = queries.by_method(user, p.branch_id, p.date_from, p.date_to)
    keys = ["in", "out", "net", "count"]
    return Result(
        columns=[
            Col(_("Payment method")),
            Col(_("Received"), "money"),
            Col(_("Paid out"), "money"),
            Col(_("Net"), "money"),
            Col(_("Count"), "int"),
        ],
        rows=[[r["method"], *[r[k] for k in keys]] for r in rows],
        totals=[_("Total"), *_total(rows, keys)],
    )


def debt(user, p) -> Result:
    rows = queries.debt_by_course(user, p.branch_id)
    keys = ["open", "overdue", "debtors"]
    return Result(
        columns=[
            Col(_("Course")),
            Col(_("Unpaid now"), "money"),
            Col(_("Overdue now"), "money"),
            Col(_("Debtors"), "int"),
        ],
        rows=[[r["course"] or _("Not tied to a course"), *[r[k] for k in keys]] for r in rows],
        totals=[_("Total"), *_total(rows, ["open", "overdue"]), ""],
        note=_("The state right now; the period filter doesn't apply."),
    )


def _conversion_rows(rows, names):
    out = []
    for r in rows:
        rate = (r["converted"] / r["total"]) if r["total"] else 0
        out.append([names(r), r["total"], r["converted"], r["lost"], rate])
    out.sort(key=lambda x: -x[1])
    return out


def _conversion_result(rows, first_label):
    total = sum(r[1] for r in rows)
    conv = sum(r[2] for r in rows)
    return Result(
        columns=[
            Col(first_label),
            Col(_("New leads"), "int"),
            Col(_("Became students"), "int"),
            Col(_("Refused"), "int"),
            Col(_("Conversion"), "percent"),
        ],
        rows=rows,
        totals=[_("Total"), total, conv, sum(r[3] for r in rows), (conv / total) if total else 0],
        note=_("Leads created in the period and what has happened to them so far."),
    )


def lead_sources(user, p) -> Result:
    names = dict(LeadSource.objects.values_list("id", "name"))
    rows = queries.leads_by(user, p.branch_id, p.date_from, p.date_to, "source_id")
    return _conversion_result(
        _conversion_rows(rows, lambda r: names.get(r["source_id"], "—")), _("Source")
    )


def lead_managers(user, p) -> Result:
    names = dict(get_user_model().objects.values_list("id", "full_name"))
    rows = queries.leads_by(user, p.branch_id, p.date_from, p.date_to, "manager_id")
    return _conversion_result(
        _conversion_rows(rows, lambda r: names.get(r["manager_id"]) or _("No manager")),
        _("Manager"),
    )


for report in (
    ReportDef(
        "oylar",
        _("Charged and collected by month"),
        _("Revenue and collections month by month."),
        "reports.view",
        monthly,
        order=10,
        group=FIN,
    ),
    ReportDef(
        "filiallar",
        _("By branch"),
        _("Charged, collected and debt per branch."),
        "reports.view",
        branches,
        order=20,
        group=FIN,
    ),
    ReportDef(
        "kurslar",
        _("By course"),
        _("Charged and collected per course."),
        "reports.view",
        courses,
        order=30,
        group=FIN,
    ),
    ReportDef(
        "tolov-usullari",
        _("By payment method"),
        _("Money in and out per payment method."),
        "reports.view",
        methods,
        order=40,
        group=FIN,
    ),
    ReportDef(
        "qarzdorlik",
        _("Debt by course"),
        _("Total and overdue debt right now."),
        "reports.view",
        debt,
        uses_period=False,
        order=50,
        group=FIN,
    ),
    ReportDef(
        "lid-manbalar",
        _("Lead conversion by source"),
        _("Which sources bring students."),
        "reports.view",
        lead_sources,
        order=60,
        group=LEADS,
    ),
    ReportDef(
        "lid-menejerlar",
        _("Lead conversion by manager"),
        _("How each manager converts leads."),
        "reports.view",
        lead_managers,
        order=70,
        group=LEADS,
    ),
):
    register_report(report)
