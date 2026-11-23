"""Report registry (docs/SPEC.md 4.4). Any module can register a report; the reports app
renders it as a table (cards on phones) with filters and an Excel download."""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Col:
    label: object
    kind: str = "text"  # text | money | int | percent | date


@dataclass
class Result:
    columns: list[Col]
    rows: list[list]
    totals: list | None = None
    note: object = ""


@dataclass(frozen=True)
class Params:
    date_from: dt.date
    date_to: dt.date
    branch_id: int | None


@dataclass(frozen=True)
class ReportDef:
    key: str
    title: object
    description: object
    permission: str
    build: Callable  # build(user, params: Params) -> Result
    uses_period: bool = True
    order: int = 100
    group: object = ""


_reports: dict[str, ReportDef] = {}


def register_report(report: ReportDef) -> None:
    _reports[report.key] = report


def get_report(key: str) -> ReportDef | None:
    return _reports.get(key)


def reports() -> list[ReportDef]:
    return sorted(_reports.values(), key=lambda r: (r.order, r.key))
