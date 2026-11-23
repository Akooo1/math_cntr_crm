from django.http import Http404
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.core import dates, excel
from apps.core.datemath import add_months, month_start
from apps.core.permissions import has_perm, perm_required, require_perm
from apps.core.reports import Params, get_report, reports


@perm_required("reports.view")
def index(request):
    visible = [r for r in reports() if has_perm(request.user, r.permission)]
    groups: dict[str, list] = {}
    for r in visible:
        groups.setdefault(str(r.group), []).append(r)
    return render(request, "reports/index.html", {"groups": groups.items()})


def _params(request) -> tuple[Params, dict]:
    today = dates.today()
    default_from = add_months(month_start(today), -5)

    def parse(name, default):
        try:
            return dates.parse_date(request.GET[name]) if request.GET.get(name) else default
        except ValueError:
            return default

    start, end = parse("dan", default_from), parse("gacha", today)
    if end < start:
        start, end = end, start
    return Params(start, end, request.branch_filter), {"dan": start, "gacha": end}


def _report(request, key):
    report = get_report(key)
    if report is None:
        raise Http404
    require_perm(request.user, report.permission)
    params, shown = _params(request)
    return report, report.build(request.user, params), shown


@perm_required("reports.view")
def report(request, key):
    rep, result, shown = _report(request, key)
    presets = []
    today = dates.today()
    for label, start in (
        (_("This month"), month_start(today)),
        (_("Last 3 months"), add_months(month_start(today), -2)),
        (_("Last 6 months"), add_months(month_start(today), -5)),
        (_("This year"), today.replace(month=1, day=1)),
    ):
        presets.append({"label": label, "dan": start, "gacha": today})
    return render(
        request,
        "reports/report.html",
        {
            "report": rep,
            "result": result,
            "shown": shown,
            "presets": presets,
            "query": request.GET.urlencode(),
        },
    )


@perm_required("reports.view")
def report_excel(request, key):
    rep, result, shown = _report(request, key)
    headers = [c.label for c in result.columns]
    kinds = ["date" if c.kind == "month" else c.kind for c in result.columns]
    rows = [list(r) for r in result.rows]
    totals = (
        [str(v) if not isinstance(v, int | float) else v for v in result.totals]
        if result.totals
        else None
    )
    content = excel.workbook(str(rep.title), headers, rows, kinds, totals)
    return excel.response(f"{rep.key}-{shown['dan']:%Y%m%d}-{shown['gacha']:%Y%m%d}", content)
