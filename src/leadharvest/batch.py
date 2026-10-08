"""Batch mode (V2, F16): many categories x locations from a CSV file or a Sheet tab.

Each row becomes an ordinary run tagged with options {"batch": name, "row": n}. Running the
same batch again skips completed rows and resumes unfinished ones, so a batch can be stopped
with Ctrl+C and simply started again.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from leadharvest.categories import Category, UnknownCategory, resolve_category
from leadharvest.geo.nominatim import LocationNotFound
from leadharvest.logging_setup import get_logger
from leadharvest.models import Run
from leadharvest.pipeline import Pipeline
from leadharvest.storage.repository import Repository

log = get_logger("batch")

MAX_JOBS = 500


class BatchError(Exception):
    """The jobs file itself is unusable (missing columns, bad values)."""


@dataclass
class Job:
    row: int
    category: str
    location: str
    limit: int | None = None
    sources: list[str] | None = None


@dataclass
class JobResult:
    job: Job
    status: str  # completed | partial | failed | skipped | error
    run_id: str | None = None
    leads: int = 0
    new: int = 0
    message: str = ""


def parse_jobs(rows: Iterable[Mapping[str, Any]]) -> list[Job]:
    """Rows with `category` and `location` (required), `limit` and `sources` (optional).

    Blank rows and rows whose category starts with '#' are ignored. Row numbers count data
    rows from 1 and identify the job when a batch is resumed, so append new rows at the end.
    """
    jobs: list[Job] = []
    errors: list[str] = []
    for index, raw in enumerate(rows, start=1):
        row = {str(k).strip().lower(): str(v if v is not None else "").strip()
               for k, v in raw.items() if k is not None}  # fmt: skip
        category, location = row.get("category", ""), row.get("location", "")
        if not category and not location:
            continue
        if category.startswith("#"):
            continue
        if not category or not location:
            errors.append(f"row {index}: needs both category and location")
            continue
        limit = None
        if row.get("limit"):
            try:
                limit = int(row["limit"])
                if not 1 <= limit <= 5000:
                    raise ValueError
            except ValueError:
                errors.append(f"row {index}: limit must be a whole number from 1 to 5000")
                continue
        sources = [s.strip() for s in row.get("sources", "").replace("|", ";").split(";")
                   if s.strip()] or None  # fmt: skip
        jobs.append(Job(index, category, location, limit, sources))
    if errors:
        raise BatchError("; ".join(errors))
    if not jobs:
        raise BatchError("no jobs found (columns needed: category, location)")
    if len(jobs) > MAX_JOBS:
        raise BatchError(f"{len(jobs)} jobs is more than the {MAX_JOBS} allowed in one batch")
    return jobs


def read_jobs_csv(path: Path) -> list[Job]:
    if not path.is_file():
        raise BatchError(f"jobs file not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = {h.strip().lower() for h in (reader.fieldnames or [])}
        if not {"category", "location"} <= headers:
            raise BatchError(f"{path} needs a header row with 'category' and 'location' columns")
        return parse_jobs(reader)


def read_jobs_sheet(worksheet: Any) -> list[Job]:
    """A Google Sheet tab with the same columns (gspread Worksheet or a compatible fake)."""
    return parse_jobs(worksheet.get_all_records())


Executor = Callable[[Run, Category], Run]


def run_batch(
    name: str,
    jobs: list[Job],
    *,
    repo: Repository,
    pipeline: Pipeline,
    categories: dict[str, Category],
    execute: Executor,
    default_limit: int,
    targets: list[str],
    default_sources: list[str],
    options: dict[str, Any],
    rerun: bool = False,
    on_job: Callable[[Job, str], None] | None = None,
) -> list[JobResult]:
    """Run every job in order. One job failing never stops the batch; Ctrl+C does."""
    results: list[JobResult] = []
    for job in jobs:
        try:
            category = resolve_category(job.category, categories)
        except UnknownCategory as exc:
            results.append(JobResult(job, "error", message=str(exc)))
            continue
        existing = repo.find_batch_run(name, job.row)
        if existing and (existing.category, existing.location) != (category.key, job.location):
            existing = None  # the row was edited since: it is a new job
        if existing and existing.status == "completed" and not rerun:
            results.append(_result(repo, job, existing, "skipped", "already completed"))
            continue
        if existing and existing.status != "completed":
            run = existing
            action = f"resuming at {run.current_step}"
        else:
            run = pipeline.create_run(
                category, job.location, limit=job.limit or default_limit, targets=targets,
                sources=job.sources or default_sources,
                options={**options, "batch": name, "row": job.row},
            )  # fmt: skip
            action = "starting"
        if on_job:
            on_job(job, action)
        try:
            finished = execute(run, category)
        except LocationNotFound as exc:
            results.append(JobResult(job, "failed", run.id, message=f"location not found: "
                                     f"{exc.location}"))  # fmt: skip
            continue
        except Exception as exc:  # recorded on the run; keep going with the next job
            log.error("batch %s row %s failed: %s", name, job.row, exc)
            results.append(JobResult(job, "failed", run.id, message=str(exc)[:200]))
            continue
        results.append(_result(repo, job, finished, finished.status, finished.error or ""))
    return results


def _result(repo: Repository, job: Job, run: Run, status: str, message: str) -> JobResult:
    return JobResult(job, status, run.id, repo.count_run_leads(run.id),
                     repo.count_new_leads(run.id), message)  # fmt: skip
