"""Google Sheets upsert (blueprint section 10.7).

- Columns are found by header name; client columns (any other header) are never written.
- One read (all values) → one batch update. Writes use RAW so nothing is evaluated.
- A "<tab> - summary" tab next to each leads tab holds `about_rows` (the XLSX About sheet). It
  is ours, so it's cleared and rewritten on every export.
- Each lead written to a tab is remembered (`SentRows`, the database's `sheet_rows`), so a row
  the client deletes stays deleted instead of coming back on the next export (decision D4).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from gspread.utils import rowcol_to_a1
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from leadharvest.exporters.base import (
    MANAGED_COLUMNS,
    ExportError,
    about_rows,
    attribution,
    lead_to_row,
)
from leadharvest.models import ExportResult, Lead, Run

MAX_TAB_LEN = 100
NEW_TAB_SUFFIX = " - new"
SUMMARY_TAB_SUFFIX = " - summary"
NEW_TAB_COLUMNS: tuple[str, ...] = ("found_on", *MANAGED_COLUMNS)


class WorksheetLike(Protocol):
    title: str
    row_count: int
    col_count: int

    def get_all_values(self) -> list[list[str]]: ...
    def batch_update(self, data: list[dict[str, Any]], **kwargs: Any) -> Any: ...
    def resize(self, rows: int | None = None, cols: int | None = None) -> Any: ...
    def freeze(self, rows: int | None = None, cols: int | None = None) -> Any: ...
    def format(self, ranges: str, cell_format: dict[str, Any]) -> Any: ...
    def set_basic_filter(self, name: str | None = None) -> Any: ...
    def update_note(self, cell: str, content: str) -> Any: ...
    def clear(self) -> Any: ...


class SentRows(Protocol):
    """Which leads were written to a tab before (storage.Repository implements it)."""

    def sheet_lead_ids(self, sheet_id: str, tab: str) -> set[str]: ...
    def add_sheet_lead_ids(self, sheet_id: str, tab: str, lead_ids: list[str]) -> None: ...


@dataclass
class SheetPlan:
    updates: list[dict[str, Any]] = field(default_factory=list)
    required_rows: int = 1
    required_cols: int = 0
    updated: int = 0
    appended: int = 0
    skipped: int = 0  # written before, then deleted by the client
    written: list[str] = field(default_factory=list)  # lead_ids of the rows written


def tab_title(category: str, area: str) -> str:
    title = re.sub(r"[\[\]\*\?:/\\]", " ", f"{category} - {area}")
    return " ".join(title.split())[:MAX_TAB_LEN] or "Leads"


def _cell_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return str(value)


def _runs(indices: list[int]) -> list[tuple[int, int]]:
    """Group sorted ints into inclusive contiguous (start, end) runs."""
    runs: list[tuple[int, int]] = []
    for i in sorted(indices):
        if runs and i == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return runs


def plan_upsert(
    grid: list[list[str]],
    rows: list[dict[str, object]],
    columns: tuple[str, ...] = MANAGED_COLUMNS,
    sent_before: set[str] | frozenset[str] = frozenset(),
) -> SheetPlan:
    """Plan writes for `rows` (dicts keyed by managed column) against the current sheet values.

    `columns` are the managed headers (must include lead_id); every other column is the
    client's and is never written. A lead in `sent_before` (written to this tab by an earlier
    export) that is no longer in the sheet was deleted by the client, so it isn't appended.

    Indices here are 0-based; ranges in the plan are A1 notation.
    """
    plan = SheetPlan()
    header = [h.strip() for h in grid[0]] if grid else []
    col_of: dict[str, int] = {}
    for idx, name in enumerate(header):
        if name in columns and name not in col_of:
            col_of[name] = idx

    used_width = max((len(r) for r in grid), default=0)
    last_used = -1
    for c in range(used_width):
        if any(c < len(r) and str(r[c]).strip() for r in grid):
            last_used = c
    next_col = last_used + 1
    for name in columns:
        if name not in col_of:
            col_of[name] = next_col
            plan.updates.append({"range": rowcol_to_a1(1, next_col + 1), "values": [[name]]})
            next_col += 1

    id_col = col_of["lead_id"]
    existing: dict[str, int] = {}
    for r in range(1, len(grid)):
        row = grid[r]
        if id_col < len(row) and row[id_col].strip():
            existing.setdefault(row[id_col].strip(), r)

    n_rows = max(len(grid), 1)
    targets: dict[int, dict[str, object]] = {}
    for row in rows:
        lead_id = str(row["lead_id"])
        if lead_id in existing:
            targets[existing[lead_id]] = row
            plan.updated += 1
        elif lead_id in sent_before:
            plan.skipped += 1
            continue
        else:
            targets[n_rows] = row
            n_rows += 1
            plan.appended += 1
        plan.written.append(lead_id)

    managed_cols = sorted(col_of[name] for name in columns)
    name_at = {col_of[name]: name for name in columns}
    for r_start, r_end in _runs(list(targets)):
        for c_start, c_end in _runs(managed_cols):
            values = [
                [_cell_value(targets[r].get(name_at[c])) for c in range(c_start, c_end + 1)]
                for r in range(r_start, r_end + 1)
            ]
            rng = f"{rowcol_to_a1(r_start + 1, c_start + 1)}:{rowcol_to_a1(r_end + 1, c_end + 1)}"
            plan.updates.append({"range": rng, "values": values})

    plan.required_rows = n_rows
    plan.required_cols = max(next_col, used_width, max(managed_cols) + 1)
    return plan


def _is_retryable(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status == 429 or (isinstance(status, int) and status >= 500)


OpenWorksheet = Callable[[str, int], WorksheetLike]


def gspread_opener(service_account_file: Path, sheet_id: str) -> OpenWorksheet:
    def open_worksheet(title: str, min_rows: int) -> WorksheetLike:
        import gspread

        client = gspread.service_account(filename=str(service_account_file))
        spreadsheet = client.open_by_key(sheet_id)
        try:
            return spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            return spreadsheet.add_worksheet(
                title=title, rows=max(100, min_rows), cols=len(MANAGED_COLUMNS) + 5
            )

    return open_worksheet


class SheetsExporter:
    name = "sheets"

    def __init__(
        self,
        open_worksheet: OpenWorksheet,
        *,
        target_label: str = "Google Sheet",
        sleep: Callable[[float], None] = time.sleep,
        attempts: int = 4,
        sent: SentRows | None = None,
        sheet_id: str = "",
    ) -> None:
        self.open_worksheet = open_worksheet
        self.target_label = target_label
        self.sent = sent  # None: every missing row is appended (no memory, e.g. tests)
        self.sheet_id = sheet_id
        self._retrying = Retrying(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=2, max=60),
            retry=retry_if_exception(_is_retryable),
            sleep=sleep,
            reraise=True,
        )

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return self._retrying(fn, *args, **kwargs)

    def _upsert(
        self, title: str, rows: list[dict[str, object]], columns: tuple[str, ...], note: str
    ) -> SheetPlan:
        try:
            ws = self._call(self.open_worksheet, title, len(rows) + 1)
            grid = self._call(ws.get_all_values)
            sent_before = self.sent.sheet_lead_ids(self.sheet_id, title) if self.sent else set()
            plan = plan_upsert(grid, rows, columns, sent_before)
            if plan.required_rows > ws.row_count or plan.required_cols > ws.col_count:
                self._call(
                    ws.resize,
                    rows=max(ws.row_count, plan.required_rows),
                    cols=max(ws.col_count, plan.required_cols),
                )
            if plan.updates:
                self._call(ws.batch_update, plan.updates, value_input_option="RAW")
            if self.sent is not None:  # only after the rows are really in the sheet
                self.sent.add_sheet_lead_ids(self.sheet_id, title, plan.written)
            self._call(ws.format, "1:1", {"textFormat": {"bold": True}})
            self._call(ws.freeze, rows=1)
            self._call(ws.set_basic_filter)
            # Data licences need attribution; a note on the header keeps the client's columns.
            self._call(ws.update_note, "A1", note)
        except Exception as exc:
            raise ExportError(f"Google Sheets export failed: {exc}") from exc
        return plan

    def export(self, leads: list[Lead], run: Run) -> ExportResult:
        title = tab_title(run.category, run.area_name or run.location)
        rows: list[dict[str, object]] = [lead_to_row(lead, run.category) for lead in leads]
        plan = self._upsert(title, rows, MANAGED_COLUMNS, attribution(run, leads))
        self._write_summary(title[: MAX_TAB_LEN - len(SUMMARY_TAB_SUFFIX)] + SUMMARY_TAB_SUFFIX,
                            about_rows(run, leads))  # fmt: skip
        return ExportResult(
            exporter=self.name,
            target=f"{self.target_label} / {title}",
            rows_updated=plan.updated,
            rows_appended=plan.appended,
            rows_skipped=plan.skipped,
        )

    def _write_summary(self, title: str, rows: list[tuple[str, str]]) -> None:
        try:
            ws = self._call(self.open_worksheet, title, len(rows))
            self._call(ws.clear)  # ours: a shorter summary leaves no stale rows below
            values = [list(row) for row in rows]
            data = [{"range": f"A1:B{len(rows)}", "values": values}]
            self._call(ws.batch_update, data, value_input_option="RAW")
            self._call(ws.format, "A:A", {"textFormat": {"bold": True}})
        except Exception as exc:
            raise ExportError(f"Google Sheets summary failed: {exc}") from exc

    def export_new(self, leads: list[Lead], run: Run) -> ExportResult:
        """Monitoring: upsert into a '<tab> - new' history tab with the date each lead was found.

        Earlier weeks' rows stay, so the tab is a running log of new businesses.
        """
        base = tab_title(run.category, run.area_name or run.location)
        title = base[: MAX_TAB_LEN - len(NEW_TAB_SUFFIX)] + NEW_TAB_SUFFIX
        found_on = run.created_at[:10]
        rows: list[dict[str, object]] = [
            {"found_on": found_on, **lead_to_row(lead, run.category)} for lead in leads
        ]
        plan = self._upsert(title, rows, NEW_TAB_COLUMNS, attribution(run, leads))
        return ExportResult(
            exporter=self.name,
            target=f"{self.target_label} / {title}",
            rows_updated=plan.updated,
            rows_appended=plan.appended,
            rows_skipped=plan.skipped,
        )
