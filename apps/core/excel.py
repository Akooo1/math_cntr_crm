"""Excel export (Excel'ga yuklash). Headers come translated; money stays numeric."""

import io
import re

from django.http import HttpResponse
from django.utils.functional import Promise
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

MONEY_FORMAT = '#,##0 "so\'m"'
PERCENT_FORMAT = "0.0%"
DATE_FORMAT = "DD.MM.YYYY"


def workbook(
    title: str, headers: list[str], rows: list[list], kinds: list[str], totals=None
) -> bytes:
    """kinds per column: text | money | int | percent (0..1 float) | date."""
    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", " ", str(title))[:31] or "Hisobot"
    ws.append([str(h) for h in headers])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows + ([totals] if totals else []):
        ws.append([_cell(v) for v in row])
    for idx, kind in enumerate(kinds, start=1):
        letter = get_column_letter(idx)
        fmt = {"money": MONEY_FORMAT, "percent": PERCENT_FORMAT, "date": DATE_FORMAT}.get(kind)
        if fmt:
            for cell in ws[letter][1:]:
                cell.number_format = fmt
        width = max(
            [len(str(headers[idx - 1]))] + [len(str(r[idx - 1])) for r in rows[:200]] + [10]
        )
        ws.column_dimensions[letter].width = min(width + 4, 60)
    if totals:
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell(v):
    # Lazy translations and SafeStrings are not str subclasses openpyxl accepts.
    if isinstance(v, Promise) or hasattr(v, "__html__"):
        return str(v)
    return v


def response(filename: str, content: bytes) -> HttpResponse:
    resp = HttpResponse(
        content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-") or "hisobot"
    resp["Content-Disposition"] = f'attachment; filename="{safe}.xlsx"'
    return resp
