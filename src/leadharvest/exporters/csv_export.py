"""CSV export: UTF-8 with BOM, formula-injection guard (blueprint section 10.7b)."""

from __future__ import annotations

import csv
from pathlib import Path

from leadharvest.exporters.base import (
    MANAGED_COLUMNS,
    OSM_ATTRIBUTION,
    PHONE_COLUMNS,
    export_basename,
    lead_to_row,
)
from leadharvest.models import ExportResult, Lead, Run

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def escape_cell(column: str, value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if column not in PHONE_COLUMNS and text.startswith(_FORMULA_PREFIXES):
        if column in ("lat", "lon", "score"):
            return text  # our own numbers, e.g. negative longitudes
        return "'" + text
    return text


class CsvExporter:
    name = "csv"

    def __init__(self, export_dir: Path) -> None:
        self.export_dir = export_dir

    def export(self, leads: list[Lead], run: Run) -> ExportResult:
        return self._write(leads, run, f"{export_basename(run)}.csv")

    def export_new(self, leads: list[Lead], run: Run) -> ExportResult:
        """Monitoring: only the leads that are new since the previous run."""
        return self._write(leads, run, f"{export_basename(run)}-new.csv")

    def _write(self, leads: list[Lead], run: Run, filename: str) -> ExportResult:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        path = self.export_dir / filename
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(MANAGED_COLUMNS)
            for lead in leads:
                row = lead_to_row(lead, run.category)
                writer.writerow([escape_cell(col, row[col]) for col in MANAGED_COLUMNS])
        path.with_suffix(".about.txt").write_text(
            f"{OSM_ATTRIBUTION}\nCategory: {run.category}\nLocation: {run.location}\n"
            f"Run ID: {run.id}\nRows: {len(leads)}\n"
            "Tip: open the .xlsx in Excel; Excel converts +63... phone numbers in CSV files.\n",
            encoding="utf-8",
        )
        return ExportResult(exporter=self.name, target=str(path), rows_appended=len(leads))
