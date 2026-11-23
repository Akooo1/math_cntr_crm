"""Excel import framework (docs/SPEC.md 6.5).

Upload -> validate every row (dry run) -> show errors per row in Uzbek -> commit all rows
in ONE transaction, or nothing. Each kind (groups, students; billing adds opening balances)
is registered here and owns its columns, row parser and writer.
"""

import io
from collections.abc import Callable
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _
from openpyxl import Workbook, load_workbook

from apps.core import audit
from apps.core.permissions import ensure_branch_access, require_perm

from ..models import ImportBatch

MAX_ROWS = 5000


@dataclass
class RowError:
    row: int  # spreadsheet row number (header = 1)
    message: str


@dataclass
class ParseResult:
    rows: list[dict] = field(default_factory=list)  # parsed, ready for commit
    errors: list[RowError] = field(default_factory=list)


@dataclass(frozen=True)
class ImportKind:
    key: str
    label: object
    columns: list  # [(header, example)] — headers are translated strings
    parse: Callable  # parse(raw_rows: list[tuple[int, dict]], ctx) -> ParseResult
    commit: Callable  # commit(rows, ctx) -> dict summary
    help_text: object = ""
    supports_update: bool = False


@dataclass
class Context:
    actor: object
    branch: object
    update_existing: bool = False
    batch: ImportBatch | None = None


_kinds: dict[str, ImportKind] = {}


def register_import_kind(kind: ImportKind) -> None:
    _kinds[kind.key] = kind


def get_kind(key: str) -> ImportKind:
    if key not in _kinds:
        raise ValidationError(_("Unknown import type."))
    return _kinds[key]


def kinds() -> list[ImportKind]:
    return list(_kinds.values())


def template_workbook(kind: ImportKind) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = str(kind.label)[:31]
    ws.append([str(h) for h, _example in kind.columns])
    ws.append([e for _h, e in kind.columns])
    for i, (h, _e) in enumerate(kind.columns, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(
            14, len(str(h)) + 4
        )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_rows(kind: ImportKind, content: bytes) -> tuple[list[tuple[int, dict]], list[RowError]]:
    """Rows as {header: value}. Column order in the file doesn't matter; headers do."""
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - any unreadable file is the same user error
        return [], [RowError(0, _("The file could not be read. Use the .xlsx template."))]
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    header = next(it, None)
    if header is None:
        return [], [RowError(0, _("The file is empty."))]
    names = [str(h).strip() if h is not None else "" for h in header]
    expected = [str(h) for h, _e in kind.columns]
    missing = [h for h in expected if h not in names]
    if missing:
        return [], [RowError(1, _("Missing columns: %(cols)s") % {"cols": ", ".join(missing)})]
    rows = []
    for number, values in enumerate(it, start=2):
        if values is None or all(v in (None, "") for v in values):
            continue
        rows.append((number, {n: v for n, v in zip(names, values, strict=False) if n}))
        if len(rows) > MAX_ROWS:
            return [], [RowError(number, _("Too many rows (more than %(n)d).") % {"n": MAX_ROWS})]
    if not rows:
        return [], [RowError(2, _("The file has no data rows."))]
    return rows, []


def _check(actor, branch):
    require_perm(actor, "import.run")
    ensure_branch_access(actor, branch.pk)


def validate_upload(*, actor, kind_key: str, branch, uploaded_file, update_existing=False):
    """Dry run: store the file and the report. Nothing else is written."""
    _check(actor, branch)
    kind = get_kind(kind_key)
    content = uploaded_file.read()
    raw, errors = read_rows(kind, content)
    ctx = Context(actor=actor, branch=branch, update_existing=update_existing)
    result = ParseResult(errors=errors)
    if not errors:
        result = kind.parse(raw, ctx)
    uploaded_file.seek(0)
    batch = ImportBatch.objects.create(
        kind=kind.key,
        file_name=uploaded_file.name[:255],
        file=uploaded_file,
        uploaded_by=actor,
        status=ImportBatch.Status.FAILED if result.errors else ImportBatch.Status.VALIDATED,
        row_count=len(raw),
        report={
            "branch_id": branch.pk,
            "update_existing": update_existing,
            "errors": [{"row": e.row, "message": str(e.message)} for e in result.errors],
            "valid_rows": len(result.rows),
        },
    )
    return batch


def commit(*, actor, batch: ImportBatch, branch):
    """Re-validate the stored file and write everything in one transaction."""
    _check(actor, branch)
    if batch.status != ImportBatch.Status.VALIDATED:
        raise ValidationError(_("This file can't be imported. Upload it again."))
    kind = get_kind(batch.kind)
    batch.file.open("rb")
    content = batch.file.read()
    batch.file.close()
    raw, errors = read_rows(kind, content)
    ctx = Context(
        actor=actor,
        branch=branch,
        update_existing=batch.report.get("update_existing", False),
        batch=batch,
    )
    with transaction.atomic():
        locked = ImportBatch.objects.select_for_update().get(pk=batch.pk)
        if locked.status != ImportBatch.Status.VALIDATED:
            raise ValidationError(_("This file can't be imported. Upload it again."))
        result = ParseResult(errors=errors) if errors else kind.parse(raw, ctx)
        if result.errors:
            locked.status = ImportBatch.Status.FAILED
            locked.report = {
                **locked.report,
                "errors": [{"row": e.row, "message": str(e.message)} for e in result.errors],
            }
            locked.save(update_fields=["status", "report"])
            return locked
        ctx.batch = locked
        summary = kind.commit(result.rows, ctx)
        locked.status = ImportBatch.Status.COMMITTED
        locked.report = {**locked.report, "summary": summary}
        locked.save(update_fields=["status", "report"])
        audit.record(
            actor,
            "students.import.commit",
            locked,
            after={"kind": locked.kind, "rows": locked.row_count, **summary},
            branch_id=branch.pk,
        )
    return locked
