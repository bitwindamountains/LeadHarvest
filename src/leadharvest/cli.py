"""Typer CLI (blueprint section 8)."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from leadharvest import __version__
from leadharvest.batch import BatchError, Job, read_jobs_csv, read_jobs_sheet, run_batch
from leadharvest.categories import Category, UnknownCategory, load_categories, resolve_category
from leadharvest.clean.normalize import (
    is_shared_domain,
    normalize_email,
    normalize_phones,
    registered_domain,
)
from leadharvest.config import ConfigError, Settings, load_settings
from leadharvest.enrich.fetcher import PoliteFetcher
from leadharvest.enrich.render import playwright_installed
from leadharvest.exporters.base import Exporter
from leadharvest.exporters.csv_export import CsvExporter
from leadharvest.exporters.hubspot_export import HubSpotExporter
from leadharvest.exporters.sheets_export import SheetsExporter, gspread_opener
from leadharvest.exporters.xlsx_export import XlsxExporter
from leadharvest.geo.nominatim import LocationNotFound
from leadharvest.http import make_client
from leadharvest.logging_setup import attach_run_log, console, detach_run_log, setup_console_logging
from leadharvest.models import ResolvedArea, Run, SearchQuery
from leadharvest.pipeline import Pipeline
from leadharvest.sources.base import SourceError
from leadharvest.sources.directory import (
    DirectoryConfigError,
    DirectorySource,
    available_directories,
    load_directory_config,
)
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository

app = typer.Typer(
    help="LeadHarvest: find businesses, enrich them from their own websites, export clean leads.",
    no_args_is_help=True,
    add_completion=False,
)

EXPORT_TARGETS = ("csv", "xlsx", "sheets", "hubspot")
EXIT_USER_ERROR = 2
EXIT_INTERRUPTED = 130


# ---- helpers --------------------------------------------------------------------------------


def _fail(message: str, code: int = EXIT_USER_ERROR) -> typer.Exit:
    console.print(f"[red]Error:[/red] {message}")
    return typer.Exit(code)


def _settings() -> Settings:
    try:
        return load_settings()
    except ConfigError as exc:
        raise _fail(str(exc)) from None


def _parse_targets(value: str, settings: Settings) -> list[str]:
    targets = [t.strip().lower() for t in value.split(",") if t.strip()]
    unknown = [t for t in targets if t not in EXPORT_TARGETS]
    if unknown or not targets:
        raise _fail(f"--to must be a comma list of {', '.join(EXPORT_TARGETS)}; got {value!r}")
    try:
        if "sheets" in targets:
            settings.require_sheets()
        if "hubspot" in targets:
            settings.require_hubspot()
    except ConfigError as exc:
        raise _fail(str(exc)) from None
    return list(dict.fromkeys(targets))


def _parse_sources(value: str) -> list[str]:
    """'osm', 'directory:<name>', or a comma list. Directory configs are validated now."""
    sources = [s.strip() for s in value.split(",") if s.strip()]
    if not sources:
        raise _fail("--sources needs at least one source (osm or directory:<name>).")
    for source in sources:
        if source == "osm":
            continue
        if not source.startswith("directory:"):
            raise _fail(f"Unknown source {source!r}. Use osm or directory:<name>.")
        try:
            load_directory_config(source.split(":", 1)[1])
        except DirectoryConfigError as exc:
            raise _fail(str(exc)) from None
    return list(dict.fromkeys(sources))


def _run_options(js: bool, mx: bool) -> dict[str, bool]:
    if js and not playwright_installed():
        raise _fail(
            "--js needs Playwright: uv sync --extra js && uv run playwright install chromium"
        )
    return {"js": js, "mx": mx}


def exporter_factory(settings: Settings):
    def build(name: str) -> Exporter:
        if name == "csv":
            return CsvExporter(settings.export_dir)
        if name == "xlsx":
            return XlsxExporter(settings.export_dir)
        if name == "sheets":
            settings.require_sheets()
            return SheetsExporter(
                gspread_opener(settings.google_service_account_file, settings.google_sheet_id)
            )
        if name == "hubspot":
            settings.require_hubspot()
            return HubSpotExporter(settings.hubspot_access_token)
        raise ValueError(f"unknown export target: {name}")

    return build


@contextmanager
def _repository(settings: Settings) -> Iterator[Repository]:
    try:
        conn = connect(settings.db_path)
    except sqlite3.Error as exc:
        raise _fail(f"Cannot open database {settings.db_path}: {exc}") from None
    try:
        yield Repository(conn)
    finally:
        conn.close()


def _category(name: str, settings: Settings) -> Category:
    try:
        return resolve_category(name, load_categories(settings.categories_file))
    except UnknownCategory as exc:
        raise _fail(str(exc)) from None


def _run_id(repo: Repository, ref: str) -> str:
    run_id = repo.resolve_run_id(ref)
    if run_id is None:
        raise _fail(f"No run matches {ref!r}. See 'leadharvest runs'.")
    return run_id


class RichReporter:
    def __init__(self, progress: Progress) -> None:
        self.progress = progress
        self.tasks: dict[str, int] = {}

    def step_started(self, step: str, total: int | None = None) -> None:
        self.tasks[step] = self.progress.add_task(step, total=total)

    def step_progress(self, step: str, done: int, total: int) -> None:
        if step in self.tasks:
            self.progress.update(self.tasks[step], completed=done, total=total)

    def step_finished(self, step: str) -> None:
        if step in self.tasks:
            task = self.tasks[step]
            total = self.progress.tasks[task].total or 1
            self.progress.update(task, completed=total, total=total)


def _progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description:<8}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def _execute_run(
    settings: Settings,
    repo: Repository,
    run: Run,
    category: Category,
    *,
    stop_after: str | None = None,
    any_country: bool = False,
) -> Run:
    """Run the pipeline with progress bars and a per-run log. Errors propagate."""
    handler = attach_run_log(settings.log_dir, run.id)
    try:
        with _progress() as progress:
            pipeline = Pipeline(
                settings,
                repo,
                exporter_factory=exporter_factory(settings),
                reporter=RichReporter(progress),
            )
            return asyncio.run(
                pipeline.execute(
                    run.id,
                    category,
                    stop_after=stop_after,  # type: ignore[arg-type]
                    any_country=any_country,
                )
            )
    except KeyboardInterrupt:
        current = repo.get_run(run.id)
        if current and current.status == "running":
            repo.update_run(run.id, status="partial", error="interrupted")
        raise
    finally:
        detach_run_log(handler)


def _execute(
    settings: Settings,
    repo: Repository,
    run: Run,
    category: Category,
    *,
    stop_after: str | None = None,
    any_country: bool = False,
) -> Run:
    """_execute_run for single-run commands: friendly messages and exit codes."""
    try:
        return _execute_run(
            settings, repo, run, category, stop_after=stop_after, any_country=any_country
        )
    except KeyboardInterrupt:
        console.print(
            f"\n[yellow]Interrupted.[/yellow] Resume with: leadharvest resume --run {run.id[:8]}"
        )
        raise typer.Exit(EXIT_INTERRUPTED) from None
    except LocationNotFound as exc:
        hint = ""
        if exc.suggestions:
            hint = " Closest matches:\n  - " + "\n  - ".join(exc.suggestions)
        raise _fail(
            f"Location not found: {exc.location!r}. Try a more specific location.{hint}"
        ) from None
    except Exception as exc:
        raise _fail(
            f"Run failed: {type(exc).__name__}: {exc}. Details: {settings.log_dir}", 1
        ) from None


def print_summary(repo: Repository, run: Run) -> None:
    stats = run.stats
    clean = stats.get("clean", {})
    enrich = stats.get("enrich", {})
    leads = repo.leads_for_run(run.id)
    with_email = sum(1 for lead in leads if lead.email)
    with_phone = sum(1 for lead in leads if lead.phone)
    statuses = repo.enrich_status_counts(run.id)
    table = Table(
        title=f"Run {run.id[:8]} — {run.category} in {run.area_name or run.location}",
        show_header=False,
    )
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Status", f"{run.status} (step: {run.current_step})")
    search = stats.get("search", {})
    found = clean.get("found", search.get("osm_records", 0))
    table.add_row("Found (raw records)", str(found))
    table.add_row(
        "Leads in run",
        f"{len(leads)} ({clean.get('new', 0)} new, {clean.get('existing', 0)} seen before)",
    )
    table.add_row("Duplicates merged", str(clean.get("duplicates_merged", 0)))
    if clean.get("truncated"):
        table.add_row("Truncated", f"yes, kept first {run.limit_n} (raise --limit for more)")
    if clean.get("suppressed"):
        table.add_row("Suppressed (forgotten)", str(clean["suppressed"]))
    table.add_row("Enrichment", ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items())) or "-")
    if leads:
        table.add_row("With email", f"{with_email} ({with_email * 100 // len(leads)}%)")
        table.add_row("With phone", f"{with_phone} ({with_phone * 100 // len(leads)}%)")
    if enrich.get("protected_emails"):
        table.add_row("Protected emails (not decoded)", str(enrich["protected_emails"]))
    if enrich.get("js_rendered"):
        table.add_row("Pages rendered with --js", str(enrich["js_rendered"]))
    score = stats.get("score", {})
    if score.get("scored"):
        table.add_row("Average score", str(score.get("average_score")))
        flags = score.get("flags") or {}
        if flags:
            table.add_row("Flags", ", ".join(f"{k}: {v}" for k, v in sorted(flags.items())))
        dropped = score.get("emails_dropped_dead_domain") or []
        if dropped:
            table.add_row("Emails dropped (dead domain)", str(len(dropped)))
    dups = len(clean.get("possible_duplicates", [])) + len(enrich.get("possible_duplicates", []))
    if dups:
        table.add_row("Possible duplicates to review", f"{dups} (see run log)")
    monitor = stats.get("monitor")
    if monitor:
        since = (
            "first run for this area"
            if not monitor.get("previous_run")
            else (f"since run {monitor['previous_run'][:8]}")
        )
        table.add_row("New since last run", f"{monitor['new_since_last_run']} ({since})")
    for result in stats.get("export_results", []):
        table.add_row(
            f"Export: {result['exporter']}",
            f"{result['target']} (+{result['rows_appended']} / ~{result['rows_updated']})",
        )
    if run.error:
        table.add_row("Error", run.error)
    console.print(table)
    if run.status == "partial":
        console.print(f"Resume with: [bold]leadharvest resume --run {run.id[:8]}[/bold]")
    if len(leads) == 0 and run.current_step == "done":
        console.print(
            "No results. Try a broader area or a related category (see 'leadharvest categories')."
        )


# ---- commands -------------------------------------------------------------------------------


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show info logs.")] = False,
) -> None:
    setup_console_logging(verbose)


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"leadharvest {__version__}")


@app.command()
def categories() -> None:
    """List available categories and their OpenStreetMap tags."""
    settings = _settings()
    table = Table("category", "label", "osm tags", "synonyms")
    for cat in load_categories(settings.categories_file).values():
        table.add_row(cat.key, cat.label, ", ".join(cat.osm_tags), ", ".join(cat.synonyms))
    console.print(table)


@app.command()
def run(
    category: Annotated[str, typer.Option(help="Category key, e.g. dentist.")],
    location: Annotated[str, typer.Option(help='Area, e.g. "Makati, Philippines".')],
    limit: Annotated[int, typer.Option(min=1, max=5000, help="Max leads in this run.")] = 200,
    to: Annotated[str, typer.Option(help="Export targets: csv,xlsx,sheets,hubspot.")] = "csv,xlsx",
    sources: Annotated[str, typer.Option(help="osm and/or directory:<name>, comma list.")] = "osm",
    js: Annotated[bool, typer.Option(help="Render near-empty JS sites with Playwright.")] = False,
    mx: Annotated[bool, typer.Option(help="Drop emails on domains without mail servers.")] = True,
    any_country: Annotated[bool, typer.Option(help="Don't restrict to LH_DEFAULT_REGION.")] = False,
) -> None:
    """Full run: search → clean → enrich → score → export."""
    settings = _settings()
    try:
        settings.require_network_identity()
    except ConfigError as exc:
        raise _fail(str(exc)) from None
    cat = _category(category, settings)
    targets = _parse_targets(to, settings)
    source_list = _parse_sources(sources)
    options = _run_options(js, mx and settings.mx_check)
    with _repository(settings) as repo:
        pipeline = Pipeline(settings, repo, exporter_factory=exporter_factory(settings))
        new_run = pipeline.create_run(
            cat, location, limit=limit, targets=targets, sources=source_list, options=options
        )
        console.print(f"Run [bold]{new_run.id[:8]}[/bold]: {cat.label} in {location}")
        result = _execute(settings, repo, new_run, cat, any_country=any_country)
        print_summary(repo, result)
        if result.status != "completed":
            raise typer.Exit(1)


@app.command()
def search(
    category: Annotated[str, typer.Option(help="Category key, e.g. dentist.")],
    location: Annotated[str, typer.Option(help='Area, e.g. "Makati, Philippines".')],
    limit: Annotated[int, typer.Option(min=1, max=5000)] = 200,
    sources: Annotated[str, typer.Option(help="osm and/or directory:<name>, comma list.")] = "osm",
    any_country: Annotated[bool, typer.Option()] = False,
) -> None:
    """Search only: resolve the location and save raw records (continue with 'resume')."""
    settings = _settings()
    try:
        settings.require_network_identity()
    except ConfigError as exc:
        raise _fail(str(exc)) from None
    cat = _category(category, settings)
    source_list = _parse_sources(sources)
    with _repository(settings) as repo:
        pipeline = Pipeline(settings, repo, exporter_factory=exporter_factory(settings))
        new_run = pipeline.create_run(
            cat, location, limit=limit, targets=["csv", "xlsx"], sources=source_list,
            options={"js": False, "mx": settings.mx_check},
        )  # fmt: skip
        result = _execute(
            settings, repo, new_run, cat, stop_after="search", any_country=any_country
        )
        found = repo.count_raw(result.id)
        console.print(
            f"Run {result.id[:8]}: saved {found} raw records. "
            f"Continue with: leadharvest resume --run {result.id[:8]}"
        )


@app.command()
def resume(
    run_ref: Annotated[
        str, typer.Option("--run", help="Run id, id prefix, or 'latest'.")
    ] = "latest",
) -> None:
    """Resume a partial or interrupted run from its current step."""
    settings = _settings()
    try:
        settings.require_network_identity()
    except ConfigError as exc:
        raise _fail(str(exc)) from None
    with _repository(settings) as repo:
        run_id = _run_id(repo, run_ref)
        existing = repo.get_run(run_id)
        assert existing is not None
        if existing.current_step == "done":
            console.print(f"Run {run_id[:8]} is already complete.")
            print_summary(repo, existing)
            return
        if "sheets" in existing.export_targets:
            _parse_targets("sheets", settings)
        cat = _category(existing.category, settings)
        console.print(f"Resuming run {run_id[:8]} at step '{existing.current_step}'")
        result = _execute(settings, repo, existing, cat)
        print_summary(repo, result)
        if result.status != "completed":
            raise typer.Exit(1)


@app.command()
def enrich(
    run_ref: Annotated[
        str, typer.Option("--run", help="Run id, id prefix, or 'latest'.")
    ] = "latest",
    retry_failed: Annotated[
        bool, typer.Option(help="Retry timeout/http_error/failed leads.")
    ] = False,
    refresh_days: Annotated[
        int | None, typer.Option(help="Re-enrich ok leads older than N days.")
    ] = None,
) -> None:
    """Enrich a run's pending leads (or retry failures / refresh stale ones)."""
    settings = _settings()
    try:
        settings.require_network_identity()
    except ConfigError as exc:
        raise _fail(str(exc)) from None
    with _repository(settings) as repo:
        run_id = _run_id(repo, run_ref)
        handler = attach_run_log(settings.log_dir, run_id)
        try:
            with _progress() as progress:
                pipeline = Pipeline(
                    settings,
                    repo,
                    exporter_factory=exporter_factory(settings),
                    reporter=RichReporter(progress),
                )
                stats = asyncio.run(
                    pipeline.enrich_only(
                        run_id, retry_failed=retry_failed, refresh_days=refresh_days
                    )
                )
        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Interrupted.[/yellow] Finished leads are saved; run the "
                "same command again to continue."
            )
            raise typer.Exit(EXIT_INTERRUPTED) from None
        finally:
            detach_run_log(handler)
        console.print(f"Enriched {stats['attempted']} leads: {stats['outcomes']}")


@app.command()
def export(
    run_ref: Annotated[
        str, typer.Option("--run", help="Run id, id prefix, or 'latest'.")
    ] = "latest",
    to: Annotated[str, typer.Option(help="Export targets: csv,xlsx,sheets.")] = "csv,xlsx",
) -> None:
    """Export a run's leads. Sheets upserts by lead_id and never touches client columns."""
    settings = _settings()
    targets = _parse_targets(to, settings)
    with _repository(settings) as repo:
        run_id = _run_id(repo, run_ref)
        existing = repo.get_run(run_id)
        assert existing is not None
        pipeline = Pipeline(settings, repo, exporter_factory=exporter_factory(settings))
        try:
            results = pipeline.export(existing, targets)
        except Exception as exc:
            raise _fail(str(exc), 1) from None
        for result in results:
            console.print(
                f"{result.exporter}: {result.target} "
                f"({result.rows_appended} appended, {result.rows_updated} updated)"
            )


def _load_jobs(settings: Settings, jobs_file: Path | None, from_sheet: str | None) -> list[Job]:
    if (jobs_file is None) == (from_sheet is None):
        raise _fail("Give a jobs CSV file or --from-sheet TAB (one of them).")
    try:
        if jobs_file is not None:
            return read_jobs_csv(jobs_file)
        settings.require_sheets()
        import gspread

        client = gspread.service_account(filename=str(settings.google_service_account_file))
        try:
            worksheet = client.open_by_key(settings.google_sheet_id).worksheet(from_sheet)
        except gspread.WorksheetNotFound:
            raise _fail(f"No tab named {from_sheet!r} in the Google Sheet.") from None
        return read_jobs_sheet(worksheet)
    except (BatchError, ConfigError) as exc:
        raise _fail(str(exc)) from None


def _batch_command(
    *,
    jobs_file: Path | None,
    from_sheet: str | None,
    name: str,
    limit: int,
    to: str,
    sources: str,
    js: bool,
    mx: bool,
    rerun: bool,
    monitor: bool,
) -> None:
    settings = _settings()
    try:
        settings.require_network_identity()
    except ConfigError as exc:
        raise _fail(str(exc)) from None
    targets = _parse_targets(to, settings)
    default_sources = _parse_sources(sources)
    options: dict[str, object] = {**_run_options(js, mx and settings.mx_check)}
    if monitor:
        options["monitor"] = True
    job_list = _load_jobs(settings, jobs_file, from_sheet)
    for job in job_list:  # validate per-row sources before anything runs
        if job.sources:
            _parse_sources(",".join(job.sources))
    categories = load_categories(settings.categories_file)
    console.print(f"Batch [bold]{name}[/bold]: {len(job_list)} job(s)")

    def on_job(job: Job, action: str) -> None:
        console.print(f"\n[bold]Row {job.row}[/bold]: {job.category} in {job.location} ({action})")

    with _repository(settings) as repo:
        pipeline = Pipeline(settings, repo, exporter_factory=exporter_factory(settings))
        try:
            results = run_batch(
                name, job_list, repo=repo, pipeline=pipeline, categories=categories,
                execute=lambda r, c: _execute_run(settings, repo, r, c),
                default_limit=limit, targets=targets, default_sources=default_sources,
                options=options, rerun=rerun, on_job=on_job,
            )  # fmt: skip
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow] Run the same command again to "
                          "continue; finished rows are skipped.")  # fmt: skip
            raise typer.Exit(EXIT_INTERRUPTED) from None

    table = Table("row", "category", "location", "status", "leads", "new", "run", "note",
                  title=f"Batch {name}")  # fmt: skip
    for res in results:
        table.add_row(
            str(res.job.row),
            res.job.category,
            res.job.location,
            res.status,
            str(res.leads),
            str(res.new),
            (res.run_id or "")[:8],
            res.message[:60],
        )
    console.print(table)
    if any(res.status not in ("completed", "skipped") for res in results):
        raise typer.Exit(1)


@app.command()
def batch(
    jobs_file: Annotated[
        Path | None, typer.Argument(help="CSV with category,location[,limit,sources] columns.")
    ] = None,
    from_sheet: Annotated[str | None, typer.Option(help="Read jobs from this Sheet tab.")] = None,
    name: Annotated[str | None, typer.Option(help="Batch name (default: file/tab name).")] = None,
    limit: Annotated[int, typer.Option(min=1, max=5000, help="Default limit per job.")] = 200,
    to: Annotated[str, typer.Option(help="Export targets: csv,xlsx,sheets,hubspot.")] = "csv,xlsx",
    sources: Annotated[str, typer.Option(help="Default sources per job.")] = "osm",
    js: Annotated[bool, typer.Option(help="Render near-empty JS sites.")] = False,
    mx: Annotated[bool, typer.Option(help="Drop emails on dead domains.")] = True,
    rerun: Annotated[bool, typer.Option(help="Run completed rows again.")] = False,
) -> None:
    """Many categories x locations in one go. Re-run the same command to resume a batch."""
    base = name or (jobs_file.stem if jobs_file else from_sheet) or "batch"
    _batch_command(jobs_file=jobs_file, from_sheet=from_sheet, name=base, limit=limit, to=to,
                   sources=sources, js=js, mx=mx, rerun=rerun, monitor=False)  # fmt: skip


def monitor_batch_name(base: str, today: date | None = None) -> str:
    """One batch per ISO week, so a weekly schedule starts fresh runs and a re-run resumes."""
    year, week, _ = (today or date.today()).isocalendar()
    return f"{base}@{year}-W{week:02d}"


@app.command()
def monitor(
    jobs_file: Annotated[
        Path | None, typer.Argument(help="CSV with category,location[,limit,sources] columns.")
    ] = None,
    from_sheet: Annotated[str | None, typer.Option(help="Read jobs from this Sheet tab.")] = None,
    name: Annotated[str | None, typer.Option(help="Monitor name (default: file/tab name).")] = None,
    limit: Annotated[int, typer.Option(min=1, max=5000, help="Default limit per job.")] = 200,
    to: Annotated[str, typer.Option(help="Export targets: csv,xlsx,sheets,hubspot.")] = "csv,xlsx",
    sources: Annotated[str, typer.Option(help="Default sources per job.")] = "osm",
    mx: Annotated[bool, typer.Option(help="Drop emails on dead domains.")] = True,
) -> None:
    """Weekly monitoring: fresh runs each ISO week plus a "New since last run" export."""
    base = name or (jobs_file.stem if jobs_file else from_sheet) or "monitor"
    _batch_command(jobs_file=jobs_file, from_sheet=from_sheet, name=monitor_batch_name(base),
                   limit=limit, to=to, sources=sources, js=False, mx=mx, rerun=False,
                   monitor=True)  # fmt: skip


async def _sample_adapter(
    settings: Settings, repo: Repository, source_name: str, query: SearchQuery, pages: int
) -> list:
    async with make_client(settings) as client:
        fetcher = PoliteFetcher(settings, client, repo=repo)
        source = DirectorySource(load_directory_config(source_name), fetcher)
        return await source.search(query, max_pages=pages)


@app.command("test-adapter")
def test_adapter(
    name: Annotated[str, typer.Argument(help="Adapter file name in config/directories/.")],
    category: Annotated[str, typer.Option(help="Category key, e.g. dentist.")] = "dentist",
    location: Annotated[str, typer.Option(help="City used for the {city} placeholder.")] = "Makati",
    pages: Annotated[int, typer.Option(min=1, max=5)] = 1,
) -> None:
    """Fetch a directory adapter's first page(s) and print 5 parsed records (blueprint W4)."""
    settings = _settings()
    try:
        settings.require_network_identity()
        load_directory_config(name)
    except (ConfigError, DirectoryConfigError) as exc:
        raise _fail(str(exc)) from None
    cat = _category(category, settings)
    city = location.split(",")[0].strip()
    query = SearchQuery(
        category=cat.key, osm_tags=cat.osm_tags, location=location, limit=50,
        area=ResolvedArea(kind="bbox", bbox=(0.0, 0.0, 0.0, 0.0), name=city),
    )  # fmt: skip
    with _repository(settings) as repo:
        try:
            records = asyncio.run(_sample_adapter(settings, repo, name, query, pages))
        except SourceError as exc:
            raise _fail(str(exc), 1) from None
    console.print(f"Parsed {len(records)} record(s) from {pages} page(s).")
    table = Table("source_ref", "name", "phone", "website", "address/street", "city")
    for r in records[:5]:
        table.add_row(
            r.source_ref[:40],
            r.name,
            "; ".join(r.phones_raw),
            r.website_raw or "",
            r.street or "",
            r.city or "",
        )
    console.print(table)
    if not records:
        console.print("No records: check the 'item' selector against the page HTML.")


@app.command("adapters")
def adapters() -> None:
    """List configured directory adapters (config/directories/*.yaml)."""
    names = available_directories()
    console.print(
        "\n".join(names)
        if names
        else "No adapters yet. Copy config/directories/_template.yaml to start one."
    )


@app.command()
def runs(limit: Annotated[int, typer.Option(min=1)] = 20) -> None:
    """List recent runs."""
    settings = _settings()
    with _repository(settings) as repo:
        table = Table("id", "created (UTC)", "category", "location", "status", "step", "leads")
        for item in repo.list_runs(limit):
            table.add_row(
                item.id[:8],
                item.created_at.replace("T", " ")[:16],
                item.category,
                item.location,
                item.status,
                item.current_step,
                str(repo.count_run_leads(item.id)),
            )
        console.print(table)


@app.command()
def forget(
    domain: Annotated[
        str | None, typer.Option(help="Website or email domain, e.g. clinic.com.ph")
    ] = None,
    phone: Annotated[str | None, typer.Option(help="Phone number in any format.")] = None,
    email: Annotated[str | None, typer.Option(help="Email address.")] = None,
    reason: Annotated[str, typer.Option(help="Recorded with the suppression.")] = "removal request",
) -> None:
    """Delete matching leads and suppress them from all future runs (privacy requests)."""
    settings = _settings()
    given = [x for x in (domain, phone, email) if x]
    if len(given) != 1:
        raise _fail("Give exactly one of --domain, --phone, --email.")
    if domain:
        kind, value = "domain", registered_domain(domain.strip().lower()) or ""
        if is_shared_domain(value):
            raise _fail(f"{value} is a shared hosting/social domain; use --email or --phone.")
    elif phone:
        kind, numbers = "phone", normalize_phones(phone, settings.default_region)
        value = numbers[0] if numbers else ""
    else:
        kind, value = "email", normalize_email(email) or ""
    if not value:
        raise _fail("That value could not be normalized; check it and try again.")
    with _repository(settings) as repo:
        deleted = repo.forget(kind, value, reason)
    console.print(
        f"Deleted {deleted} lead(s) and suppressed {kind} {value}. Future runs will skip it."
    )
    console.print("Remember to remove the rows from any Sheets or files already delivered.")


@app.command()
def purge(
    not_seen_days: Annotated[int, typer.Option(min=1, help="Delete leads not seen for N days.")],
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation.")] = False,
) -> None:
    """Delete leads not seen in any run for N days (retention)."""
    settings = _settings()
    if not yes:
        typer.confirm(f"Delete leads not seen in the last {not_seen_days} days?", abort=True)
    with _repository(settings) as repo:
        deleted = repo.purge(not_seen_days)
    console.print(f"Purged {deleted} lead(s).")


if __name__ == "__main__":  # pragma: no cover
    app()
